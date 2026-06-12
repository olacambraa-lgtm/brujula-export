"""Cliente DataComex con las dos vías verificadas empíricamente
(docs/research/datacomex-extraccion.md):

- Vía A — API oficial (token JWT): maestras abiertas sin token + ObtenerDatos.
- Vía B — cadena CSV pública (sin cuenta): Index → ResultQueryData → CsvList
  con la misma cookie ASP.NET. Límite verificado 2026-06-11: el producto
  flujos × periodos × países × tarics seleccionados debe ser ≤ ~30.000
  combinaciones (29.100 OK / 32.010 falla); si se excede, el POST devuelve 200
  con el texto "la selección es demasiado amplia" y CsvList sirve el resultado
  ANTERIOR de la sesión (caché), de ahí la verificación anti-stale de abajo.
"""

import csv
import html
import io
import re
import time

import requests

API_BASE = "https://comercio.serviciosmin.gob.es/DatacomexAPI"
WEB_BASE = "https://datacomex.comercio.es"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 60
PAUSE = 0.7  # pausa cortés entre llamadas
RETRIES = 3

# Límite empírico de la vía CSV (ver docstring del módulo).
CSV_COMBO_LIMIT = 30000


class CsvLimitError(Exception):
    """La selección excede el límite de filas del formulario web."""


class CsvChainError(Exception):
    """La cadena Index → ResultQueryData → CsvList no devolvió lo esperado."""


def _request(method, url, **kwargs):
    """Petición con reintentos (3 intentos, backoff 2s/4s) y pausa cortés."""
    kwargs.setdefault("timeout", TIMEOUT)
    session = kwargs.pop("session", None)
    do = session.request if session else requests.request
    kwargs.setdefault("headers", {})
    kwargs["headers"].setdefault("User-Agent", USER_AGENT)
    last_exc = None
    for attempt in range(RETRIES):
        try:
            resp = do(method, url, **kwargs)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            time.sleep(PAUSE)
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            if attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    raise last_exc


# ---------------------------------------------------------------------------
# Maestras abiertas (sin token)
# ---------------------------------------------------------------------------

def _get_master(endpoint):
    resp = _request("GET", f"{API_BASE}/{endpoint}")
    resp.raise_for_status()
    return resp.json()


def get_paises():
    """[{"Id": "001", "Pais": "Francia", "UE": "UE27"}, ...]"""
    return _get_master("ObtenerPaises")


def get_provincias():
    """[{"Provincia": "Zaragoza", "CodProvincia": "50"}, ...]"""
    return _get_master("ObtenerProvincias")


def get_periodos():
    """[{"Periodo": ..., "CodPeriodo": "202501", "Nivel": "2", "DatosDefinitivos": bool}, ...]"""
    return _get_master("ObtenerPeriodos")


def get_tarics():
    """[{"Taric": "2204", "TaricPadre": "22", "Nombre": "...", "Nivel": "2"}, ...] (~74k filas)"""
    return _get_master("ObtenerTarics")


def get_flujos():
    """[{"Flujo": "EXPORT", "CodFlujo": "E"}, {"Flujo": "IMPORT", "CodFlujo": "I"}]"""
    return _get_master("ObtenerFlujos")


# ---------------------------------------------------------------------------
# Vía A — API con token
# ---------------------------------------------------------------------------

def login(email, password):
    """POST IniciarSesion → JWT. 403 si las credenciales son incorrectas."""
    resp = _request("POST", f"{API_BASE}/IniciarSesion",
                    json={"email": email, "password": password})
    if resp.status_code == 403:
        raise PermissionError(f"Credenciales DataComex rechazadas: {resp.text.strip()}")
    resp.raise_for_status()
    # La respuesta es el token (texto plano o JSON con el token).
    text = resp.text.strip().strip('"')
    return text


def obtener_datos(f, pe, pa, ta, token, pr=None):
    """GET ObtenerDatos. Devuelve la lista JSON o None si se excede el límite
    de ~1M filas (la API responde null sin error). Con ta=AT4, pe debe ser UN
    único periodo."""
    params = {"access_token": token, "f": f, "pe": pe, "pa": pa, "ta": ta}
    if pr is not None:
        params["pr"] = pr
    resp = _request("GET", f"{API_BASE}/ObtenerDatos", params=params)
    if resp.status_code == 401:
        raise PermissionError("Token DataComex no válido o caducado (401)")
    resp.raise_for_status()
    return resp.json()  # list | None


# ---------------------------------------------------------------------------
# Vía B — cadena CSV pública (sin cuenta)
# ---------------------------------------------------------------------------

class CsvSession:
    """Sesión del formulario público /Data/Index.

    La cadena obligatoria es: GET Index (cookie) → POST ResultQueryData
    (chk_export=on Y chk_import=on SIEMPRE, X-Requested-With) → GET CsvList.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        resp = _request("GET", f"{WEB_BASE}/Data/Index", session=self.session)
        resp.raise_for_status()
        # Nombres exactos de los checkboxes de país (con acentos decodificados):
        # [PaisOrigen].[001 Francia], ...
        self.country_fields = [
            html.unescape(n)
            for n in re.findall(r'name="(\[PaisOrigen\]\.\[[^"]+\])"', resp.text)
        ]
        if not self.country_fields:
            raise CsvChainError("No se encontraron checkboxes de país en /Data/Index")

    def _country_fields_for(self, codes):
        """codes=None → todos los países; si no, filtra por código DataComex."""
        if codes is None:
            return self.country_fields
        wanted = set(codes)
        fields = [f for f in self.country_fields
                  if f.split("[", 2)[2].split(" ", 1)[0] in wanted]
        if len(fields) != len(wanted):
            found = {f.split("[", 2)[2].split(" ", 1)[0] for f in fields}
            raise CsvChainError(f"Códigos de país sin checkbox: {wanted - found}")
        return fields

    def query(self, periods, taric_codes=None, countries=None):
        """Ejecuta una consulta y devuelve el texto CSV (ya decodificado).

        periods: lista de códigos de periodo ('2024' anual o '202401' mensual).
        taric_codes: lista de códigos TARIC de 4 dígitos (árbol jerarquia=1);
                     None → Total Taric.
        countries: lista de códigos DataComex ('001', ...); None → todos.
        """
        country_fields = self._country_fields_for(countries)
        combos = 2 * len(periods) * len(country_fields) * max(len(taric_codes or []), 1)
        if combos > CSV_COMBO_LIMIT:
            raise CsvLimitError(
                f"Selección de {combos} combinaciones > límite {CSV_COMBO_LIMIT}")

        form = [("chk_export", "on"), ("chk_import", "on")]
        form += [(f"year_[{p}]", "on") for p in periods]
        form += [(f, "on") for f in country_fields]
        if taric_codes:
            form.append(("jerarquiaTaric", "1"))
            form += [(f"[Taric].&[{c}]", "on") for c in taric_codes]
        else:
            form.append(("jerarquiaTaric", "0"))
            form.append(("totalTaric", "on"))

        resp = _request("POST", f"{WEB_BASE}/Data/ResultQueryData", data=form,
                        headers={"X-Requested-With": "XMLHttpRequest"},
                        session=self.session, timeout=300)
        resp.raise_for_status()
        if "demasiado amplia" in resp.text:
            raise CsvLimitError("El servidor rechazó la selección por exceder "
                                "el límite de filas")

        csv_resp = _request("GET", f"{WEB_BASE}/Data/CsvList",
                            session=self.session, timeout=300)
        if csv_resp.status_code != 200:
            raise CsvChainError(f"CsvList devolvió HTTP {csv_resp.status_code}")
        text = csv_resp.content.decode("latin-1")

        # Anti-stale: CsvList cachea el último resultado VÁLIDO de la sesión.
        # Verificamos que tarics Y periodos devueltos pertenecen a la selección
        # (un CSV obsoleto puede repetir los mismos códigos con otros meses).
        rows = parse_csv(text)
        expected = set(taric_codes) if taric_codes else {"Total Taric"}
        got = {row["taric"] for row in rows}
        if got and not got <= expected:
            raise CsvChainError(f"CSV obsoleto de la caché de sesión: "
                                f"tarics inesperados {sorted(got - expected)[:5]}")
        expected_periods = set(periods)
        bad_periods = set()
        for r in rows:
            code = (f"{r['year']}{r['month']:02d}" if r["month"] is not None
                    else str(r["year"]))
            # Un periodo anual solicitado ('2024') cubre sus filas mensuales.
            if code not in expected_periods and str(r["year"]) not in expected_periods:
                bad_periods.add(code)
        if bad_periods:
            raise CsvChainError(
                f"CSV obsoleto de la caché de sesión: periodos inesperados "
                f"{sorted(bad_periods)[:5]}")
        return text


def _to_float(value):
    """Decimal con coma → float; vacío (secreto estadístico/sin dato) → None."""
    value = value.strip()
    if not value:
        return None
    return float(value.replace(".", "").replace(",", ".")) if "," in value \
        else float(value)


def parse_csv(text):
    """Parsea el CSV de CsvList (latin-1 ya decodificado, sep ';', decimal coma,
    CRLF, todas las celdas entrecomilladas y ';' final de línea).

    Columnas: flujo_codigo;flujo_nombre;periodo_anio;periodo_mes;
    periodo_provisional;pais_codigo;pais_nombre;taric;euros;kilos

    Devuelve lista de dicts con: flow ('E'/'I'), year (int), month (int|None),
    is_provisional (bool, de 'P'/'D'), country_code, country_name, taric,
    euros (float|None), kilos (float|None).
    """
    reader = csv.reader(io.StringIO(text), delimiter=";", quotechar='"')
    header = next(reader, None)
    if not header or header[0] != "flujo_codigo":
        raise CsvChainError(f"Cabecera CSV inesperada: {header}")
    rows = []
    for raw in reader:
        if not raw or not raw[0]:
            continue
        rows.append({
            "flow": raw[0],
            "year": int(raw[2]),
            "month": int(raw[3]) if raw[3].strip() else None,
            "is_provisional": raw[4] == "P",
            "country_code": raw[5],
            "country_name": raw[6],
            "taric": raw[7],
            "euros": _to_float(raw[8]),
            "kilos": _to_float(raw[9]),
        })
    return rows
