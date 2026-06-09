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
    "Petrobras":        "33000167000101",
    "BNDES":            "33657248000189",
    "Caixa Economica":  "00360305000104",
    "Banco do Brasil":  "00000000000191",
    "CEDAE":            "34558841000140",
    "Correios":         "34028316000103",
    "Transpetro":       "02230805000113",
    "Casa da Moeda":    "33802884000135",
    "Furnas":           "23274194000119",
    "Eletronuclear":    "42540245000130",
    "IplanRIO":         "08781563000100",
    "Comlurb":          "42498600000148",
    "Nuclep":           "30651535000130",
}

def date_range(days_past=90, days_future=180):
    hoje = datetime.now()
    return (
        (hoje - timedelta(days=days_past)).strftime('%Y%m%d'),
        (hoje + timedelta(days=days_future)).strftime('%Y%m%d')
    )

HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Referer': 'https://pncp.gov.br/'
}

async def fetch_pncp(params: dict):
    url = 'https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params, headers=HEADERS)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None async def pncp(request):
    q          = request.query_params.get('q', '')
    uf         = request.query_params.get('uf', '')
    modalidade = request.query_params.get('modalidade', '')
    pagina     = request.query_params.get('pagina', '1')

    di, df = date_range()
    params = {'dataInicial': di, 'dataFinal': df, 'pagina': pagina, 'tamanhoPagina': '20'}
    if q:          params['q'] = q
    if uf:         params['uf'] = uf
    if modalidade: params['codigoModalidadeContratacao'] = modalidade

    try:
        data = await fetch_pncp(params)
        if data:
            return JSONResponse(data)
        return JSONResponse({'error': 'PNCP sem resposta', 'data': []}, status_code=502)
    except Exception as e:
        return JSONResponse({'error': str(e), 'data': []}, status_code=500)

async def busca(request):
    q           = request.query_params.get('q', '')
    uf          = request.query_params.get('uf', '')
    modalidade  = request.query_params.get('modalidade', '')
    pagina      = request.query_params.get('pagina', '1')
    so_estatais = request.query_params.get('estatais', 'false').lower() == 'true'

    di, df = date_range(days_past=120, days_future=365)
    keywords = [k.strip() for k in q.split(',') if k.strip()] if q else ['']

    tasks = []
    if so_estatais:
        for nome, cnpj in ESTATAIS.items():
            for kw in keywords[:3]:
                params = {'dataInicial': di, 'dataFinal': df, 'pagina': pagina, 'tamanhoPagina': '10', 'cnpjOrgao': cnpj}
                if kw: params['q'] = kw
                tasks.append(fetch_pncp(params))
    else:
        for kw in keywords:
            params = {'dataInicial': di, 'dataFinal': df, 'pagina': pagina, 'tamanhoPagina': '20'}
            if kw:         params['q'] = kw
            if uf:         params['uf'] = uf
            if modalidade: params['codigoModalidadeContratacao'] = modalidade
            tasks.append(fetch_pncp(params))

    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    seen = set()
    items = []
    for r in results_raw:
        if isinstance(r, Exception) or not r:
            continue
        lista = r.get('data') or r.get('content') or []
        for item in lista:
            key = item.get('numeroControlePNCP') or str(item.get('id', ''))
            if key and key not in seen:
                seen.add(key)
                items.append(item)

    items.sort(key=lambda x: x.get('dataAberturaProposta') or x.get('dataPublicacaoPncp') or '')

    return JSONResponse({'total': len(items), 'data': items[:50]})
async def comprasnet(request):
    q      = request.query_params.get('q', '')
    uf     = request.query_params.get('uf', '')
    pagina = request.query_params.get('pagina', '1')

    params = {'noPagina': pagina, 'qtResultadosPorPagina': 20}
    if q:  params['noPalavraChave'] = q
    if uf: params['coUf'] = uf

    url = 'https://dadosabertos.compras.gov.br/modulo-pesquisa-avancada/api/1/operacoes/consultar-licitacao'
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers={'Accept': 'application/json'})
            if resp.status_code == 200:
                return JSONResponse({'source': 'comprasnet', 'data': resp.json()})
            return JSONResponse({'error': f'ComprasNet {resp.status_code}', 'data': {}}, status_code=resp.status_code)
    except Exception as e:
        return JSONResponse({'error': str(e), 'data': {}}, status_code=500)

async def estatais(request):
    return JSONResponse({
        'total': len(ESTATAIS),
        'estatais': [{'nome': n, 'cnpj': c} for n, c in ESTATAIS.items()]
    })

async def bacen(request):
    indices = {'IPCA': 433, 'IGP-M': 189, 'INPC': 432, 'Selic': 11}
    hoje   = datetime.now()
    inicio = (hoje - timedelta(days=365)).strftime('%d/%m/%Y')
    fim    =  hoje.strftime('%d/%m/%Y')

    resultado = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for nome, codigo in indices.items():
            try:
                url = f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados'
                resp = await client.get(url, params={'formato': 'json', 'dataInicial': inicio, 'dataFinal': fim})
                if resp.status_code == 200:
                    dados = resp.json()
                    if dados:
                        ultimo = dados[-1]
                        resultado[nome] = {
                            'ultimo_valor':  float(ultimo.get('valor', 0)),
                            'ultima_data':   ultimo.get('data'),
                            'acumulado_12m': round(sum(float(d.get('valor', 0)) for d in dados[-12:]), 4),
                            'serie_6m':      dados[-6:]
                        }
            except Exception as e:
                resultado[nome] = {'erro': str(e)}

    return JSONResponse({'indices': resultado})

async def health(request):
    return JSONResponse({
        'status': 'ok',
        'rotas': ['/pncp', '/comprasnet', '/busca', '/estatais', '/bacen']
    })

app = Starlette(routes=[
    Route('/pncp',       pncp),
    Route('/comprasnet', comprasnet),
    Route('/busca',      busca),
    Route('/estatais',   estatais),
    Route('/bacen',      bacen),
    Route('/health',     health),
])

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['GET'], allow_headers=['*'])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run(app, host='0.0.0.0', port=port)