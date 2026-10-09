# 🇧🇷 CXTV Brasil → Lista M3U para SS IPTV

Lista M3U gerada automaticamente a partir de [cxtv.com.br/tv/paises/tvs-brasil](https://www.cxtv.com.br/tv/paises/tvs-brasil).

## Características

- Atualização automática a cada **6 horas** (GitHub Actions)
- Mantém apenas canais **ativos**
- Remove canais offline
- Adiciona novos canais encontrados
- Categorias iguais às do site (Filmes, Notícias, Esportes, Variedades, etc.)
- Formato otimizado para **SS IPTV** (`group-title`, `tvg-logo`, `tvg-name`)

## Como usar no SS IPTV

1. Após o deploy no GitHub, copie a URL raw da lista:
   ```
   https://raw.githubusercontent.com/SEU-USUARIO/cxtv-brasil-m3u/main/brasil.m3u
   ```
2. No SS IPTV → **External Playlist** → cole a URL acima.

## Deploy no GitHub

1. Crie um repositório novo (ex: `cxtv-brasil-m3u`)
2. Faça upload de todos os arquivos desta pasta (mantenha a estrutura)
3. Vá em **Settings → Actions → General** e habilite “Read and write permissions”
4. Vá em **Actions** e rode o workflow manualmente a primeira vez
5. Depois disso ele atualiza sozinho a cada 6 horas

## Limitação importante

O site usa Cloudflare. O scraper usa `cloudscraper`, mas em alguns momentos o desafio pode falhar.  
Se a lista ficar vazia, rode o workflow manualmente ou ajuste o script.

## Licença

Uso educacional / pessoal. Respeite os termos do site de origem.
