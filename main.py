import os
import json
import asyncio
from datetime import datetime, timedelta
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import uvicorn

async def pncp(request):
    q          = request.query_params.get('q', '')
    uf         = request.query_params.get('uf', '')
    modalidade = request.query_params.get('modalidade', '')
    pagina     = request.query_params.get('pagina', '1')

    hoje = datetime.now()
    past = hoje - timedelta(days=90)
    fut  = hoje + timedelta(days=180)
    fmt  = lambda d: d.strftime('%Y%m%d')

    params = {
        'dataInicial': fmt(past),
        'dataFinal':   fmt(fut),
        'pagina':      pagina,
        'tamanhoPagina': '20'
    }
    if q:          params['q'] = q
    if uf:         params['uf'] = uf
    if modalidade: params['codigoModalidadeContratacao'] = modalidade

    url = 'https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao'
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
        'Referer': 'https://pncp.gov.br/'
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            return JSONResponse({'error': f'PNCP {resp.status_code}', 'data': []}, status_code=resp.status_code)
    except Exception as e:
        return JSONResponse({'error': str(e), 'data': []}, status_code=500)

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

async def health(request):
    return JSONResponse({'status': 'ok', 'service': 'editallab-proxy'})

app = Starlette(routes=[
    Route('/pncp',       pncp),
    Route('/comprasnet', comprasnet),
    Route('/health',     health),
])

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['GET'],
    allow_headers=['*'],
)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run(app, host='0.0.0.0', port=port)
