"""Gera cartões únicos de atividade pública e dos privados autorizados."""

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- PROFILE_STATS_START -->"
END = "<!-- PROFILE_STATS_END -->"
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
REPO = re.compile(r"[A-Za-z0-9._-]+\Z")


class StatsError(Exception):
    """Mensagem segura para logs públicos."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = build_opener(NoRedirect)
        self.last_search = 0.0

    def get(self, path, params=None):
        if path.startswith("/search/"):
            delay = 2.1 - (time.monotonic() - self.last_search)
            if delay > 0:
                time.sleep(delay)
            self.last_search = time.monotonic()
        url = "https://api.github.com" + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self.token,
            "User-Agent": "profile-combined-stats",
            "X-GitHub-Api-Version": "2026-03-10",
        })
        try:
            with self.opener.open(request, timeout=25) as response:
                data = response.read()
        except HTTPError as exc:
            raise StatsError(f"Falha na API do GitHub (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError):
            raise StatsError("Falha de conexão com a API do GitHub.") from None
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise StatsError("Resposta inválida da API do GitHub.") from None


def config(root=ROOT, environment=None):
    values = dict(os.environ if environment is None else environment)
    if values.get("GITHUB_ACTIONS", "").lower() != "true":
        env_file = root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    raise StatsError("O .env está malformado.")
                key, value = line.split("=", 1)
                key = key.strip()
                if key in {"PROFILE_STATS_USER", "PROFILE_STATS_TOKEN", "PROFILE_STATS_REPOS"}:
                    values.setdefault(key, value.strip().strip('"').strip("'"))
    user = values.get("PROFILE_STATS_USER", "").strip()
    token = values.get("PROFILE_STATS_TOKEN", "").strip()
    raw = values.get("PROFILE_STATS_REPOS", "").strip()
    if not LOGIN.fullmatch(user) or not token or not raw:
        raise StatsError("Configure usuário, token e lista privada nos Secrets ou no .env local.")
    repos = []
    for entry in raw.split(","):
        parts = entry.strip().split("/")
        if len(parts) != 2 or not LOGIN.fullmatch(parts[0]) or not REPO.fullmatch(parts[1]) or parts[1] in {".", ".."}:
            raise StatsError("A lista privada deve usar owner/repo, separados por vírgula.")
        name = "/".join(parts)
        if name.lower() not in {value.lower() for value in repos}:
            repos.append(name)
    return user, token, repos


def search(api, endpoint, query):
    def fetch(page):
        result = api.get(endpoint, {
            "q": query, "per_page": 100, "page": page,
            "sort": "author-date" if endpoint == "/search/commits" else "created",
            "order": "asc",
        })
        if not isinstance(result, dict) or result.get("incomplete_results") is not False:
            raise StatsError("Busca incompleta; cartões anteriores preservados.")
        if not isinstance(result.get("items"), list):
            raise StatsError("Lista inválida na busca do GitHub.")
        return result
    first = fetch(1)
    count = first.get("total_count")
    if not isinstance(count, int) or count < 0 or count > 1000:
        raise StatsError("Busca com mais de 1.000 resultados anuais; cartões anteriores preservados.")
    items = list(first["items"])
    for page in range(2, (count + 99) // 100 + 1):
        items.extend(fetch(page)["items"])
    if len(items) != count:
        raise StatsError("Busca mudou durante a paginação; tente novamente.")
    return items


def collect(api, user, repos, today):
    repo_visibility = {}
    for name in repos:
        metadata = api.get("/repos/" + name)
        if not isinstance(metadata, dict) or metadata.get("private") is not True or metadata.get("full_name", "").lower() != name.lower():
            raise StatsError("Repositório privado inacessível ou renomeado.")
        repo_visibility[name.lower()] = True
    account = api.get("/users/" + user)
    try:
        first_year = date.fromisoformat(account["created_at"][:10]).year
    except (KeyError, TypeError, ValueError):
        raise StatsError("Data da conta GitHub inválida.") from None
    if first_year > today.year:
        raise StatsError("Data da conta GitHub inválida.")
    allowed = {name.lower() for name in repos}
    totals, total_events, days, active_repos = Counter(), 0, set(), set(repos)
    for year in range(first_year, today.year + 1):
        start, end = f"{year}-01-01", f"{year}-12-31"
        queries = [
            ("commits", "/search/commits", f"author:{user} author-date:{start}..{end}"),
            ("prs", "/search/issues", f"type:pr author:{user} created:{start}..{end}"),
            ("issues", "/search/issues", f"type:issue author:{user} created:{start}..{end}"),
        ]
        for kind, endpoint, query in queries:
            for item in search(api, endpoint, query):
                if not isinstance(item, dict):
                    raise StatsError("Resultado de busca inválido.")
                if kind == "commits":
                    repository = item.get("repository")
                    if not isinstance(repository, dict):
                        raise StatsError("Resultado sem repositório.")
                    name, private = repository.get("full_name"), repository.get("private")
                else:
                    repository_url = item.get("repository_url", "")
                    prefix = "https://api.github.com/repos/"
                    suffix = repository_url[len(prefix):] if isinstance(repository_url, str) and repository_url.startswith(prefix) else ""
                    parts = suffix.split("/")
                    if len(parts) != 2 or not LOGIN.fullmatch(parts[0]) or not REPO.fullmatch(parts[1]):
                        raise StatsError("URL de repositório inválida na busca.")
                    name = "/".join(parts)
                    if name.lower() not in repo_visibility:
                        metadata = api.get("/repos/" + name)
                        if not isinstance(metadata, dict) or not isinstance(metadata.get("private"), bool) or metadata.get("full_name", "").lower() != name.lower():
                            raise StatsError("Visibilidade do repositório não verificável.")
                        repo_visibility[name.lower()] = metadata["private"]
                    private = repo_visibility[name.lower()]
                if not isinstance(name, str) or not isinstance(private, bool):
                    raise StatsError("Visibilidade do repositório não verificável.")
                if private and name.lower() not in allowed:
                    continue
                timestamp = ((item.get("commit") or {}).get("author") or {}).get("date") if kind == "commits" else item.get("created_at")
                try:
                    day = date.fromisoformat(timestamp[:10])
                except (TypeError, ValueError):
                    raise StatsError("Data de atividade inválida.") from None
                if day > today:
                    continue
                total_events += 1
                if day.year == today.year:
                    totals[kind] += 1
                days.add(day)
                active_repos.add(name)
    languages = Counter()
    for name in sorted(active_repos, key=str.lower):
        data = api.get("/repos/" + name + "/languages")
        if not isinstance(data, dict):
            raise StatsError("Linguagens inválidas na API do GitHub.")
        for language, size in data.items():
            if not isinstance(language, str) or not isinstance(size, int) or size < 0:
                raise StatsError("Linguagens inválidas na API do GitHub.")
            languages[language] += size
    return totals, total_events, days, languages


def streaks(days, today):
    current = longest = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous == day - timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
        if day in {today, today - timedelta(days=1)}:
            current = run
    return current, longest


def shell(title, subtitle, content, height):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{height}" viewBox="0 0 720 {height}" role="img" aria-label="{escape(title)}">
<style>
.title{{fill:#f4fff4;font:700 22px Arial,sans-serif}}.sub{{fill:#b4c9b8;font:13px Arial,sans-serif}}
.label{{fill:#bfd3c3;font:13px Arial,sans-serif}}.value{{fill:#8df3a0;font:700 34px Arial,sans-serif}}
.bar{{fill:#5dcf77;transform-origin:left;animation:grow 1.1s ease-out both}}.fade{{animation:appear .8s ease-out both}}
@keyframes appear{{from{{opacity:0;transform:translateY(5px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes grow{{from{{opacity:0;transform:scaleX(0)}}to{{opacity:1;transform:scaleX(1)}}}}
@media(prefers-reduced-motion:reduce){{.bar,.fade{{animation:none}}}}
</style>
<rect width="719" height="{height-1}" x=".5" y=".5" rx="16" fill="#141b16" stroke="#304637"/>
<text class="title" x="30" y="44">{escape(title)}</text><text class="sub" x="30" y="67">{escape(subtitle)}</text>
{content}</svg>
'''


def metrics(title, subtitle, entries):
    parts = []
    for index, (label, value) in enumerate(entries):
        x = 30 + 225 * index
        parts.append(f'<g class="fade" style="animation-delay:{index*140}ms"><text class="value" x="{x}" y="142">{value:,}</text><text class="label" x="{x}" y="169">{escape(label)}</text></g>')
    return shell(title, subtitle, "\n".join(parts), 198)


def language_card(languages):
    total = sum(languages.values())
    parts = []
    if not total:
        parts.append('<text class="label" x="30" y="116">Sem linguagens detectadas.</text>')
    for index, (language, size) in enumerate(sorted(languages.items(), key=lambda row: (-row[1], row[0]))[:5]):
        y = 104 + index * 38
        percent = 100 * size / total
        width = max(2, round(410 * size / total))
        parts.append(f'<text class="label" x="30" y="{y}">{escape(language[:28])}</text><rect x="215" y="{y-15}" width="410" height="12" rx="6" fill="#304637"/><rect class="bar" x="215" y="{y-15}" width="{width}" height="12" rx="6" style="animation-delay:{index*120}ms"/><text class="label" x="640" y="{y}">{percent:.1f}%</text>')
    return shell("Linguagens dos projetos analisados", "Bytes dos repositórios; não apenas código de minha autoria", "\n".join(parts), 310)


def replace_readme(readme):
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise StatsError("Marcadores dos cartões não encontrados no README.")
    begin = readme.index(START)
    end = readme.index(END, begin) + len(END)
    block = f"""{START}
![Atividade pública e privada autorizada](assets/profile-activity.svg)

## Estatísticas

![Commits, pull requests e issues públicos e privados](assets/profile-contributions.svg)

![Linguagens dos projetos públicos e privados autorizados](assets/profile-languages.svg)

<sub>Inclui atividade pública e privados autorizados. Dias ativos: commits, PRs ou issues. Totais do ano em UTC. Nomes dos projetos privados não são publicados.</sub>
{END}"""
    return readme[:begin] + block + readme[end:]


def write_if_changed(path, content):
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main():
    user, token, repos = config()
    today = datetime.now(timezone.utc).date()
    totals, total_events, days, languages = collect(GitHub(token), user, repos, today)
    current, longest = streaks(days, today)
    outputs = {
        "profile-activity.svg": metrics("Atividade no GitHub", "Público + privados autorizados · histórico de contribuições", [("Contribuições", total_events), ("Sequência atual", current), ("Maior sequência", longest)]),
        "profile-contributions.svg": metrics("Estatísticas", f"{today.year} UTC · público + privados autorizados", [("Commits", totals["commits"]), ("Pull requests", totals["prs"]), ("Issues", totals["issues"])]),
        "profile-languages.svg": language_card(languages),
    }
    published = "".join(outputs.values()).lower()
    if any(value.lower() in published for value in [token, *repos]):
        raise StatsError("Publicação interrompida: informação privada detectada no cartão.")
    readme = ROOT / "README.md"
    updated = replace_readme(readme.read_text(encoding="utf-8"))
    for name, content in outputs.items():
        write_if_changed(ROOT / "assets" / name, content)
    write_if_changed(readme, updated)
    print("Cartões combinados atualizados sem publicar credenciais ou nomes privados.")


if __name__ == "__main__":
    try:
        main()
    except StatsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Erro inesperado; nenhum dado privado foi exibido no log.", file=sys.stderr)
        raise SystemExit(1) from None
