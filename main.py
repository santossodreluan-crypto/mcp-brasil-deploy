import os
import asyncio
from datetime import datetime, timedelta
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import uvicorn

ESTATAIS = {
    "Petrobras":       "33000167000101",
    "BNDES":           "33657248000189",
    "Caixa Economica": "00360305000104",
    "Banco do Brasil": "00000000000191",
    "CEDAE":           "34558841000140",
    "Correios":        "34028316000103",
    "Transpetro":      "02230805000113",
    "Casa da Moeda":   "33802884000135",
    "Furnas":          "23274194000119",
    "Eletronuclear":   "42540245000130",
    "IplanRIO":        "08781563000100",
    "Comlurb":         "42498600000148",
    "Nuclep":          "30651535000130",
}

def date_range(days_past=90, days_future=180):
    hoje = datetime.now()
    return (
        (hoje - timedelta(days=days_past)).strftime('%Y%m%d'),
        (hoje + timedelta(days=days_future)).strftime('%Y%m%d')
    )

HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0',
    'Referer': 'https://pncp.gov.br/'
}

async def fetch_pncp(params):
    url = 'https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None

async def pncp(request):
    q  = request.query_params.get('q', '')
    uf = request.query_params.get('uf', '')
    md = request.query_params.get('modalidade', '')
    pg = request.query_params.get('pagina', '1')
    di, df = date_range()
    p = {'dataInicial': di, 'dataFinal': df, 'pagina': pg, 'tamanhoPagina': '20'}
    if q:  p['q'] = q
    if uf: p['uf'] = uf
    if md: p['codigoModalidadeContratacao'] = md
    try:
        data = await fetch_pncp(p)
        if data:
            return JSONResponse(data)
        return JSONResponse({'error': 'PNCP sem resposta', 'data': []}, status_code=502)
    except Exception as e:
        return JSONResponse({'error': str(e), 'data': []}, status_code=500)

async def busca(request):
    q   = request.query_params.get('q', '')
    uf  = request.query_params.get('uf', '')
    md  = request.query_params.get('modalidade', '')
    pg  = request.query_params.get('pagina', '1')
    est = request.query_params.get('estatais', 'false').lower() == 'true'
    di, df = date_range(120, 365)
    kws = [k.strip() for k in q.split(',') if k.strip()] if q else ['']
    tasks = []
    if est:
        for cnpj in ESTATAIS.values():
            for kw in kws[:3]:
                p = {'dataInicial': di, 'dataFinal': df, 'pagina': pg, 'tamanhoPagina': '10', 'cnpjOrgao': cnpj}
                if kw: p['q'] = kw
                tasks.append(fetch_pncp(p))
    else:
        for kw in kws:
            p = {'dataInicial': di, 'dataFinal': df, 'pagina': pg, 'tamanhoPagina': '20'}
            if kw:  p['q'] = kw
            if uf:  p['uf'] = uf
            if md:  p['codigoModalidadeContratacao'] = md
            tasks.append(fetch_pncp(p))
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    seen = set()
    items = []
    for r in raw:
        if isinstance(r, Exception) or not r:
            continue
        for item in (r.get('data') or r.get('content') or []):
            key = item.get('numeroControlePNCP') or str(item.get('id', ''))
            if key and key not in seen:
                seen.add(key)
                items.append(item)
    items.sort(key=lambda x: x.get('dataAberturaProposta') or x.get('dataPublicacaoPncp') or '')
    return JSONResponse({'total': len(items), 'data': items[:50]})

async def comprasnet(request):
    q  = request.query_params.get('q', '')
    uf = request.query_params.get('uf', '')
    pg = request.query_params.get('pagina', '1')
    p = {'noPagina': pg, 'qtResultadosPorPagina': 20}
    if q:  p['noPalavraChave'] = q
    if uf: p['coUf'] = uf
    url = 'https://dadosabertos.compras.gov.br/modulo-pesquisa-avancada/api/1/operacoes/consultar-licitacao'
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=p, headers={'Accept': 'application/json'})
            if r.status_code == 200:
                return JSONResponse({'source': 'comprasnet', 'data': r.json()})
            return JSONResponse({'error': str(r.status_code), 'data': {}}, status_code=r.status_code)
    except Exception as e:
        return JSONResponse({'error': str(e), 'data': {}}, status_code=500)

async def estatais_route(request):
    return JSONResponse({'total': len(ESTATAIS), 'estatais': [{'nome': n, 'cnpj': c} for n, c in ESTATAIS.items()]})

async def bacen(request):
    indices = {'IPCA': 433, 'IGPM': 189, 'INPC': 432, 'Selic': 11}
    hoje = datetime.now()
    ini = (hoje - timedelta(days=365)).strftime('%d/%m/%Y')
    fim = hoje.strftime('%d/%m/%Y')
    res = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for nome, cod in indices.items():
            try:
                url = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados'.format(cod)
                r = await client.get(url, params={'formato': 'json', 'dataInicial': ini, 'dataFinal': fim})
                if r.status_code == 200:
                    d = r.json()
                    if d:
                        res[nome] = {
                            'ultimo_valor': float(d[-1].get('valor', 0)),
                            'ultima_data': d[-1].get('data'),
                            'acumulado_12m': round(sum(float(x.get('valor', 0)) for x in d[-12:]), 4),
                            'serie_6m': d[-6:]
                        }
            except Exception as e:
                res[nome] = {'erro': str(e)}
    return JSONResponse({'indices': res})

async def health(request):
    return JSONResponse({'status': 'ok', 'rotas': ['/pncp', '/comprasnet', '/busca', '/estatais', '/bacen']})

app = Starlette(routes=[
    Route('/pncp',       pncp),
    Route('/comprasnet', comprasnet),
    Route('/busca',      busca),
    Route('/estatais',   estatais_route),
    Route('/bacen',      bacen),
    Route('/health',     health),
])
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['GET'], allow_headers=['*'])

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))