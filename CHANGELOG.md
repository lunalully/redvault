# Changelog

All notable changes to REDVAULT are documented here. The project follows a pragmatic version sequence; it is pre-1.0 and the content catalog is incomplete.

## [1.8.2] — 2026-11-18

Auditoria completa dos 97 labs e da plataforma: cada lab foi iniciado pelo
`lab_manager` (sandbox do `bwrap` incluso), crawleado em GET e POST.

### Fixed

- **`logic-negative-cart` respondia `500` na página inicial.** A rota `/` lia `session["balance"]` antes de `init()` semear o valor, então todo visitante novo (sessão vazia) recebia `KeyError`. O teste de exploit não pegava porque começava direto no `POST /add`. O teste agora abre `/` primeiro.
- **Scripts inline das trilhas bloqueados pela CSP.** `learning_paths.html` ("NOVA TRILHA") e `learning_path_detail.html` ("Notas") traziam `<script>` inline fora do hash da CSP, então nada acontecia ao clicar. A lógica foi movida para `static/js/app.js`.
- **Botão "Imprimir / salvar PDF" do certificado não funcionava.** Usava `onclick="window.print()"`, que a CSP (sem `'unsafe-inline'`) bloqueia. Virou `.js-print` no `app.js`.
- **Botão "Reset" do lab sumia depois de usado.** `stop()` escondia Parar/Reset e nada os reexibia, embora o lab voltasse ao ar. `setLabUI` agora reabilita os dois quando o lab está ativo.
- **Contador "Labs em execução" perdia os parênteses após 15s.** O polling gravava `3` onde o template renderiza `(3)`. Agora mantém o formato.
- **`scripts/start-lan.sh` falhava em instalação que segue o tutorial.** Rodava `python3 run.py` com o python do sistema (`No module named fastapi`), mesmo com as dependências no `.venv`. Agora usa `.venv/bin/python3` quando existe; o `--stop` reconhece qualquer `run.py`.

### Tests

- `test_platform.py::test_inline_scripts_and_handlers_respect_csp` passou a cobrir **todos** os templates (scripts inline e handlers `on*`), não só o pre-paint da sidebar.
- Regressão de cold-start em `test_labs.py::test_logic_negative_cart`.
- Suíte completa: **9/9 módulos**, e auditoria de 97/97 labs sem erro 5xx em GET e POST.

## [1.8.1] — 2026-11-18

### Fixed

- **"Iniciar lab" falhava quando a plataforma roda dentro do `.venv`.** `lab_manager` resolvia o interpretador dos labs com `shutil.which("python3")`, que com o venv ativo aponta para `.venv/bin/python3`. Como o `bwrap` só liga `/usr`, `/bin`, `/lib`, `/lib64` e `/etc`, todo lançamento morria com `bwrap: execvp .../redvault/.venv/bin/python3: No such file or directory`. Agora os labs usam um interpretador de sistema (`/usr/bin/python3`) que consiga `import flask`; se só houver Flask dentro do venv, o prefixo do venv é montado dentro do sandbox. Novo override `REDVAULT_LAB_PYTHON`.

### Tests

- Regressão em `tests/test_lan_mode.py::test_lab_never_uses_the_platform_venv_outside_the_sandbox`.

## [1.8.0] — 2026-11-14

Primeira versão pública do projeto.

### Added

- **Licença MIT** (`LICENSE`) para o código da plataforma, com as licenças de terceiros documentadas à parte.
- **README em pt-BR** com os números atuais do catálogo, biblioteca e trilhas, capturas de tela reais em `docs/images/` e instruções de importação da biblioteca.
- **Apresentação do projeto** em `docs/APRESENTACAO.md`, uma versão de leitura corrida para vitrine.

### Changed

- **`data/` saiu do controle de versão.** O banco SQLite, o `secret.key` que deriva as flags e o estado dos labs nunca mais são versionados; o `.gitignore` passou a ignorar `/data/` inteiro e o histórico foi reescrito para remover o que já havia sido commitado.
- **Chave de flags rotacionada.** A primeira inicialização de uma instalação nova gera a própria chave.
- `SECURITY.md` agora encaminha relatos de falha na plataforma para o canal privado do GitHub.

### Tests

- Suíte completa: **9/9 módulos, 199 testes**.

## [1.7.2] — 2026-11-14

### Fixed

- **Labs objetivos falhavam na UI real (49 de 97).** A linha de `lab_sessions` só era criada depois de o processo do lab subir, então cada lab recebia `LAB_SESSION_ID=0` e todo `lab.objective()` era recusado (`403`): a flag certa era reconhecida, mas a plataforma pedia "estado de exploração exigido" para sempre. Os testes de exploit não pegavam porque rodam o lab direto, sem callback. A sessão agora é gravada antes do `Popen`, e o laboratório reporta na mesma sessão.
- **Plataforma caía ao iniciar/deixar um lab.** `active_for`/`lab_on_port` iteravam o dicionário `_labs` ao vivo; o polling de status do front mutava o dicionário durante a iteração e disparava `RuntimeError: dictionary changed size during iteration`, derrubando o processo inteiro. A iteração passou a usar uma cópia.
- **Estado do lab compartilhado entre sessões.** duas sessões do mesmo desafio iniciadas no mesmo segundo dividiam o diretório de estado (log e captura se sobrescreviam). Cada sessão agora tem diretório próprio.
- **Logs do lab vazavam para o log do serviço.** Dentro do sandbox, o stdout do lab ia para o log do uvicorn; agora vai para `<state>/lab.log`, com o motivo de cada recusa de objetivo registrado no mesmo arquivo.
- **Callbacks recusados eram invisíveis.** `/internal/lab-callback` registra a recusa com sessão e chave, e o logger `redvault.*` passou a ter handler próprio (o uvicorn só configura os loggers dele; avisos de trilhas e recusas de lab ficavam sem saída).
- **Nenhum lab com XSS registrava objetivo.** O bot do Selenium rodava dentro do event loop do FastAPI; enquanto o Chromium visitava a página (5+ s), a plataforma ficava bloqueada e o callback do próprio lab (`/collect` → `/internal/lab-callback`) estourava em `TimeoutError`. A visita agora roda em thread pool e o callback do lab é atendido em paralelo.
- **Botão "Iniciar lab" preso em "PROVISIONANDO…"** quando o polling de status falhava; e o polling agora espera o lab responder, não apenas a linha "ativa".
- `objective_states` recebia linhas duplicadas para a mesma (usuário, desafio, flag); a gravação passou a ser um UPSERT sobre a chave única.
- O bot do Chromium herda o grupo de processos do serviço; passou a rodar em sessão própria, para parar junto com o servidor.

### Added

- **Dois labs de SQL injection que estavam sem teste**: `sqli-order-by-case` e `sqli-stacked-update` agora têm teste de exploit próprio.
- Dica do lab de XSS refletido corrigida: um espaço no payload vira `+` na URL e quebra o script; o exemplo agora usa `%2B`.

### Tests

- `tests/test_platform.py`: **17 testes** (antes 14) — sessão do lab no ambiente do processo, callback registrando objetivo, concorrência de start/stop.
- `tests/test_labs_phase3.py`: **36 testes** (antes 34).
- Suíte completa: **9/9 módulos, 199 testes**.

## [1.7.1] — 2026-11-13

### Fixed

- **Termos técnicos no Learning Paths apareciam com crase literal.** Enunciados de avaliação, títulos de atividade, competências do módulo e critérios/evidências do capstone são agora renderizados por `inline_md()`: só `código` entre crases vira `<code>`, todo o resto é escapado (sem negrito, itálico ou HTML vindo do currículo). Três enunciados foram reescritos para não depender de `+`, `||` ou `*` dentro do código — o conteúdo e a resposta aceita não mudaram.
- **Crase sem par no currículo agora falha na validação.** `_check_code_spans` em `app/lp_schema.py` rejeita enunciados, títulos, competências e critérios com crase ímpar, em vez de engolir o resto da frase na renderização.
- Links de destino de atividade (título do documento de KB) também passam pela formatação, padronizando a exibição.

### Tests

- `tests/test_learning_paths.py`: **41 testes** (antes 38) — renderização inline, código no enunciado dentro da página e rejeição de crase sem par.
- `tests/test_kb_hacktricks.py`: **10 testes** (antes 8) — verifica que os 24 documentos próprios são encontrados pelo FTS5 e pela busca da biblioteca.
- Suíte completa: **9/9 módulos, 193 testes**.

## [1.7.0] — 2026-11-13

### Added

- **Trilhas 09–18 no Learning Paths: Análise de Malware, Forense Digital, Cloud e Containers, Segurança Mobile, Exploit Development, Engenharia Reversa, Criptografia Aplicada, OSINT, Red Team e IoT e Embarcados.** A Fase 3 acrescenta **40 módulos, 74 disciplinas e 322 atividades** (total do programa: **18 trilhas, 78 módulos, 151 disciplinas, 788 atividades**). Cada trilha tem avaliação, capstone obrigatório com critérios e pré-requisitos verificados contra o banco real.
- **14 documentos próprios (pt-BR)** para as lacunas apontadas pelo audit, com 40 referências primárias verificadas por HTTP na data da escrita: YARA, execução fileless, cadeia de custódia/linha do tempo, memória com Volatility, IAM, serverless, Ghidra, anti-depuração, proteções de binário, HMAC/integridade, PKI, e três de OSINT (metodologia, superfície externa, pessoas e organizações). Total de documentos próprios: **24**.
- **25 categorias de KB novas** para as áreas da Fase 3 (`malware-analysis`, `forensics-memory`, `crypto-pki`, `osint-infra`, `red-team-infra`, `iot-protocols`, …), em grupos próprios.
- **`DOMAIN_LABELS`** em `app/lp_web.py`: os filtros de domínio da página de trilhas passam a exibir rótulo pt-BR em vez da chave interna (`binexp` → `EXPLOIT DEV`).
- **Novos testes de idioma e de escopo**: `test_curriculum_text_is_portuguese`, `test_ui_labels_are_portuguese`, `test_no_internal_keys_leak_into_the_ui`, `test_recommendation_kinds_are_labelled`, mais cinco da Fase 3 (escopo, pré-requisitos, ausência de lab inventado, equipamento declarado e caminho em software para exercício bloqueado).

### Fixed

- **Rótulos internos vazando para a tela.** A página de trilhas e a de recomendações imprimiam a chave crua da recomendação (`NEXT ACTIVITY`); a distribuição por tipo imprimia `THEORY`/`EXERCISES` nos cartões e no painel lateral da trilha. Agora usam `RECOMMENDATION_LABELS` e `KIND_LABELS`.
- **Página `kb_index.html`**: bloco `{% if q %}`/`{% else %}` desbalanceado derrubava a renderização com filtro de busca.
- **Contador "DISPONÍVEIS"** na página de trilhas contava trilhas com pré-requisito atendido, o que sugeria "trilhas existentes". Renomeado para **LIBERADAS**.

### Tests

- `tests/test_learning_paths.py` passou de 33 para **38 testes**. Suíte completa: **9/9 módulos, 188 testes**.

## [1.6.0] — 2026-11-13

### Added

- **Trilhas 05–08 no Learning Paths: Active Directory, Network, Wireless e Hardware.** A Fase 2 acrescenta **16 módulos, 34 disciplinas e 218 atividades** (total do programa: **8 trilhas, 38 módulos, 77 disciplinas, 466 atividades**). AD ancora nos 50 documentos `active-directory-methodology`; Network nos 209 de serviços de rede e na metodologia de rede; Wireless nos 31 documentos de Wi-Fi e nos de RFID/BLE/sub-GHz; Hardware nos 35 de hardware/acesso físico e de firmware.
- **Campo `lp_activities.equipment`.** Toda atividade da Fase 2 declara o que precisa fisicamente: `software`, `simulated`, `optional` ou `required`, validado no schema (`VALID_EQUIPMENT`) e exibido como badge na trilha. Atende ao requisito de não pressupor equipamento: a trilha Hardware tem 40 atividades só-software, 1 simulada e 4 que exigem aparelho — e cada uma destas diz no texto que fica bloqueada sem ele e qual exercício em software cobre o conceito.
- **Cinco documentos próprios (pt-BR) de hardware**, com fonte primária e 5 referências verificadas cada: reconhecimento de placa, identificação de componentes/datasheet, fluxo sigrok/PulseView, análise de firmware com Ghidra e fundamentos de SDR com prática sem transmissor.
- **Cinco categorias de KB** (`hardware`, `hardware-recon`, `hardware-signals`, `hardware-firmware`, `hardware-rf`) em grupo próprio.
- **`default_equipment()`** em `scripts/lp_builders.py`: preenche a classe de equipamento das atividades que não declararam uma, para que um campo vazio nunca signifique "não se sabe".

### Fixed

- Slugs de KB com ~100 caracteres são truncados de forma inconsistente na importação; o currículo agora usa o valor exato do banco em vez de concatenar prefixo.
- `estimated_hours` da trilha Network (31 h) não batia com a soma das atividades (38 h).
- Descrição da trilha Hardware continha marcação Markdown num campo renderizado como texto puro.

### Tests

- `tests/test_learning_paths.py` passou de 24 para **29 testes**: escopo da Fase 2, pré-requisitos existentes, equipamento declarado em toda atividade, separação software/equipamento na trilha Hardware, e renderização do badge. A checagem de ordem passou a comparar conjuntos e exigir prioridades distintas. Suíte: **9/9 módulos, 179 testes**.

## [1.5.0] — 2026-11-13

### Added

- **Integração completa do HackTricks (edição PT-BR) na biblioteca.** O HackTricks mantém a tradução em uma **branch separada** (`pt`), não no `main`. `scripts/import_kb.py --source hacktricks --path <clone-pt>` importa essa edição para o `/kb`: **1.144 documentos** em **20 categorias** (Pentest Web, Serviços de Rede, Hardening Linux/macOS/Windows, Cloud, Blockchain, Mobile, Binário, Reversão, IA, …), **1.239 payloads** extraídos e **762 imagens** localizadas. A árvore de navegação espelha o `SUMMARY.md`; os títulos usam o H1 do próprio documento (que é traduzido), porque o `SUMMARY.md` do upstream segue em inglês.
- **Detecção de idioma pela branch.** `BRANCH_LANGUAGES` mapeia `pt`/`pt-br` → `pt-BR` e `main`/`master` → `en`. Documentos importados da branch `pt` entram como `language = 'pt-BR'` e `translation_status = 'translated'`, com bloco de atribuição em português.
- **Importador dedicado `app/kb_hacktricks.py`.** Limpa as diretivas `{{#include}}` (o banner de treinamento/patrocínio não é conteúdo), reescreve links relativos `.md` para `/kb/d/<slug>`, converte imagens relativas para `/static/hacktricks/...` (a CSP do app só permite imagens mesma-origem) e registra commit, path e URL de origem por documento.
- **Créditos e licença NC visíveis.** Cada documento importado recebe um bloco de atribuição a **Carlos Polop e contribuidores** com link para a CC BY-NC 4.0, e o leitor mostra um aviso "Uso não comercial". A página de fontes distingue licenças permissivas de licenças NC.
- **Coluna `kb_sources.noncommercial_reuse`.** Separa "redistribuível" (MIT) de "reutilizável só para uso não comercial com atribuição" (CC BY-NC). O gate permissivo continua recusando tudo que não é nem uma coisa nem outra.

### Fixed

- A licença do HackTricks não é mais "(sem licença declarada)": é **CC BY-NC 4.0**. `register_sources()` agora atualiza metadados (antes só inseria), e roda no boot, então instalações antigas também são corrigidas.
- Migração aditiva para SQLite: colunas novas em tabelas existentes são criadas com `ALTER TABLE` no `init_db()`, já que `create_all` não altera tabelas existentes.

### Tests

- Novo módulo `tests/test_kb_hacktricks.py` (8 testes): parsing do SUMMARY, registro da licença NC, skip de `todo/` e `LICENSE.md`, atribuição + remoção do banner, detecção de idioma pela branch (PT-BR/translated), reescrita de links, localização de imagens, idempotência preservando corpos revisados, e o aviso NC no leitor e na página de fontes. Suite: 8/8 módulos verdes.

## [1.4.0] — 2026-11-13

### Added

- **Biblioteca técnica (Academy 2.0), in `/kb`.** A searchable, cross-linked knowledge base beside the original `/academy`: a hierarchical catalog (7 groups, 99 categories), a document reader with a per-document table of contents, a payload library with copy buttons, and a provenance page listing every upstream source with its licence and commit. The original Academy and its 17 articles are untouched.
- **Real import from PayloadsAllTheThings (MIT).** `scripts/import_kb.py --path <clone>` reads a local checkout offline, records the exact commit SHA, the original path, the licence and the author per document, and copies the upstream `LICENSE` into `content/kb_licenses/`. No network access during import, so a sync is reproducible. Imported text is stored **verbatim in English** with `translation_status = 'untranslated'`; the pagination, navigation and provenance UI are in pt-BR.
- **Licence gate.** `kb_sources` marks each upstream project `redistributable`. PayloadsAllTheThings is `True` (MIT); HackTricks (no declared licence) and OWASP WSTG (CC BY-SA) are `False` and are refused by the importer with `ImportRefused`. Non-redistributable projects appear only as links and as our own PT-BR synthesis, never as copied text.
- **FTS5 search.** SQLite's `unicode61 remove_diacritics 2` tokeniser, every term quoted and prefix-matched, terms ANDed. Searching `union based` or `jinja2` finds text inside documents, not just titles, and returns a highlighted snippet. Malformed input (`"`, `AND OR`, `'; DROP TABLE`) returns an empty list instead of an error.
- **Translation states and sync that never loses human work.** `untranslated → translated → reviewed`. `apply_upstream_change()` refreshes untranslated documents in place and, for a reviewed translation, only records the new upstream hash and sets `review_status = 'needs_review'`. A document whose upstream file disappeared is marked `upstream_removed`, never deleted.
- **Docs ↔ labs in both directions.** 291 explicit links from documents to platform challenges (`kb_topic_links`), and every lab page now shows **ESTUDAR A TÉCNICA** pointing at the document that explains it.
- **Payload extraction with context.** Fenced blocks under a technique heading become payload rows only when they contain something runnable; prose, markdown headings and credit lines are rejected. Each payload keeps its technique, language, context, expected result and source URL. 477 payloads from 135 documents.

### Fixed

- Imported sections mapped to the same category (e.g. `XSLT Injection` and `External Variable Modification`) produced colliding slugs. Slugs are now derived from the full relative path (`patt-<section>-<file>`), unique by construction.
- Imported categories were all landing in `Web Application Security`. Imported-only sections now declare a group (`CATEGORY_GROUPS`), and `seed_categories()` treats the canonical tree as the source of truth for grouping, so JWT lives under API Security and account takeover under Authentication.
- The reader repeated the document H1 as the first TOC entry. The duplicate is pruned and its children promoted; documents that start at H2 keep their TOC.
- The document sidebar grew past the viewport on long pages (the XSS page has 80+ headings). It now scrolls internally with the source link pinned.
- `/kb/payloads` rendered all payloads in one response. It is paginated (40 per page) with a real count.

### Tests

- New module `tests/test_kb.py` (15 tests): import provenance and commit SHA, licence gate, FTS search inside bodies, hostile query syntax, payload context, reviewed-translation preservation, `upstream_removed`, page rendering, category hierarchy, TOC pruning and payload pagination. The importer is tested against a tiny local git repository, so the suite never needs the network or a 14 MB checkout. Suite: 153 tests, 7 modules, all green.

## [1.3.0] — 2026-11-13

### Added

- **Runaway-traffic detection.** Each lab reports its real request count to `/internal/lab-traffic`; the platform keeps the counters (so the lab cannot forge them) and classifies the load as `normal`, `warn` (≥300 req/s) or `abort` (≥1500 req/s over a 10 s window). Above the warn threshold the lab writes `[traffic] WARN/ABORT: N req/s` to its log and adds `X-Redvault-Traffic` to its responses; the first `abort` is recorded as a `lab_abuse` activity entry.
- **Hard lifetime ceiling** (`REDVAULT_LAB_MAX_LIFETIME`, default 2 h) next to the idle timeout. A forgotten lab no longer stays exposed on a LAN-widened bind indefinitely.
- `scripts/bruteforce_load.py` measures what a brute force actually costs: requests/second and Mbps, and how that relates to the LAN. Measured on the reference machine: ~440 req/s ≈ 23 Mbps against the OTP lab, with an 8-worker client; the real bottleneck is the lab's single-process Flask, not the network.
- The lab panel now states both shutdown conditions ("X min sem tráfego ou Yh de vida").

### Fixed

- **Real traffic now counts as activity.** `touch()` was only called from the status endpoint, so a lab being attacked from another machine was reaped after 45 minutes of dashboard inactivity. `/internal/lab-traffic` touches it per report.
- The first traffic reporter spawned one thread per request; under a brute force the Flask worker pool was saturated and most reports were lost (a 4,000-request run registered 1). Replaced by a counter plus a single background reporter.

### Tests

- New module `tests/test_traffic.py` (5 tests): baseline rates stay `normal`, the abort banner fires exactly once, the sliding window stays bounded, brute-force traffic keeps the lab from being reaped, and labs expose `X-Redvault-Traffic`. Suite: 127 tests, 6 modules, all green.

## [1.2.0] — 2026-11-13

### Added

- **Opt-in LAN sharing for the lab range.** `REDVAULT_LAB_BIND` (default `127.0.0.1`) and `REDVAULT_LAB_PUBLIC_HOST` let a second computer on the same network open `http://<host-ip>:<lab-port>/` and attack the lab directly, without a VPN, while the dashboard stays on loopback. Lab cards advertise the LAN address, the room page shows a warning that the range accepts LAN clients, and the lab footer switches from `LOCAL ONLY` to `LAN SHARED`.
- `lab_url()` centralises how a lab address is built; `LAB_BIND` is passed to every lab process and honoured by both lab runtimes (`labkit` and the `serve_lab` proxy).

### Security notes

- Default behaviour is unchanged: labs bind to loopback, and `tests/test_lan_mode.py` asserts that a loopback lab refuses LAN connections.
- LAN mode is documented as a trusted-network-only option in `SECURITY.md`. The platform itself remains loopback-only and unauthenticated; widening `REDVAULT_HOST` is still not supported.

### Tests

- New module `tests/test_lan_mode.py`: starts a real lab with `REDVAULT_LAB_BIND=0.0.0.0`, reaches it through the host's non-loopback address, checks the LAN warning in the room page and asserts loopback labs stay unreachable on the LAN. Suite: 125 tests, 5 modules, all green.

## [1.1.0] — 2026-11-12

### Added

- **Each target now has its own room page at `/lab/<slug>`.** Every challenge and machine opens full screen, the way a TryHackMe room or a HackTheBox machine page does, instead of living only inside the dashboard panel. The page carries the whole briefing — objective, rules, start/open the lab, flag submission, hints, walkthrough, notes and references — but with its own top bar (brand, target title, exits to the catalog and the dashboard) and no sidebar.
- `app/templates/lab_base.html`: standalone layout for the room page. `challenge_detail.html` extends `lab_base.html` or `base.html` depending on the mode, so there is still a single source of truth for the content.
- Entry points: an `ABRIR` button on every card in `/challenges` and `/machines`, plus a `PÁGINA DO DESAFIO` tag in the panel detail header. The room page does not link to itself.

### Tests

- `test_dedicated_lab_pages_are_full_screen` checks that `/lab/<slug>` renders `body.lab-mode` with the room top bar, no `<aside class="sidebar">`, the panel detail still offering `PÁGINA DO DESAFIO`, and an unknown slug returning 404. Suite: 122 tests, 4 modules, all green.

## [1.0.0] — 2026-11-12

### Changed

- **Full pt-BR localisation.** The web interface, all 97 lab manifests (titles, summaries, briefings, objectives, rules, flag labels, hints, walkthroughs, root causes, mitigations and reference descriptions), the 17 academy articles, the glossary, learning paths, tool library, CVE index, achievements and every server-side message (API errors, flashes, activity log, flag validation) are now in Brazilian Portuguese. Security vocabulary stays in English (IDOR, BOLA, SSRF, SSTI, JWT, CSRF, SQL injection, payload, header, token, …); code, commands, payloads, URLs, identifiers and values the lab applications use literally are never translated.
- `DIFFICULTY_LABELS`, `LEVELS`, `CATEGORY_META` and `SOURCE_TYPES` in `app/config.py` now carry pt-BR labels; difficulty badges, challenge types (`MÁQUINA`/`REALISTA`/`DESAFIO`), academy article levels, the environment ledger and the command palette all render those labels instead of raw keys.
- `ACHIEVEMENTS` are seeded in pt-BR and existing rows are updated in place on startup.

### Fixed

- Difficulty badges and challenge kinds no longer leak raw English slugs (`HARD`, `MACHINE`) into the UI.
- `macros.html` received the translated label explicitly, so the badge macro does not depend on undefined template globals.

### Tests

- Assertions updated to the pt-BR strings; `test_primary_ui_pages_render` now checks that difficulty, kind and the CVE index render translated text and never raw English keys. Suite: 118 tests, 4 modules, all green.

## [0.9.0] — 2026-11-12

### Changed

- **The login screen is gone.** REDVAULT is a single-operator, loopback-only installation, so the password gate only got in the way. Every request is now served as the local operator, created automatically on first start (name configurable with `REDVAULT_OPERATOR`, default `operator`). `/login`, `/setup` and `/logout` redirect to the dashboard.
- Browser sessions are no longer an authentication factor: the `rv_session` cookie only carries the CSRF token. `/settings/session` (formerly `/settings/password`) rotates that token and revokes the other sessions.
- `bcrypt` removed from `requirements.txt`; the `users.password_hash` column is kept for schema compatibility and stays empty.

### Security notes

- CSRF protection is unchanged and still enforced on every mutating form and API call; a request without the token returns 403.
- Because there is no authentication, `REDVAULT_HOST` must stay on loopback. Binding to a public interface would expose the operator dashboard and every intentionally vulnerable lab.

### Fixed

- **The operator dashboard showed challenges they never solved.** Platform tests imported the app before their own `REDVAULT_DATA` override could win, so a run against the real database wrote progress, submissions and achievements into `data/redvault.db` (5 items appeared completed on 2026-11-12). `tests/conftest.py` now refuses to start when `REDVAULT_DATA` points at the repository `data/` directory (or is unset), and standalone lab tests get a throwaway directory. The affected progress was cleared with the in-app reset (Settings → Danger zone), and the guard now blocks that class of test at startup.

### Tests

- `test_first_run_validation_and_setup` and `test_login_logout_and_csrf` replaced by `test_local_operator_has_no_login` and `test_csrf_still_required_for_mutating_requests`.
- `test_login_throttling_blocks_after_repeated_failures` replaced by `test_no_login_route_and_single_operator`.
- Suite unchanged in size: 118 tests, 4 modules, all green.

## [0.8.0] — 2026-11-12

### Added

- **34 new challenge labs** and **2 new machines** (97 catalog items total, 89 challenges + 8 machines):
  - XSS: `xss-csp-nonce-bypass`, `xss-dom-clobber`, `xss-csp-jsonp`.
  - Client-side: `client-prototype-pollution`, `client-clickjacking-frame`, `client-websocket-csrf`.
  - API: `api-graphql-field-auth`, `api-batch-endpoint-auth`.
  - Upload: `upload-archive-traversal`, `upload-content-type-confusion`, `upload-polyglot-image`.
  - Authentication: `auth-jwt-jku-injection`, `auth-password-reset-poison`, `auth-mfa-bypass-response`, `auth-sso-assertion-replay`.
  - Access control: `access-http-parameter-pollution`, `access-trust-proxy-header`.
  - SQL injection: `sqli-stacked-update`, `sqli-order-by-case`.
  - Advanced: `adv-http-host-header-reset`, `adv-csrf-token-reuse`, `adv-cache-key-normalization`.
  - Server-side: `server-ssti-jinja-sandbox` (customised Jinja sandbox escape), `server-deserialization-pickle` (signed-but-forgeable pickle session cookie).
  - Business logic: `logic-coupon-race`, `logic-signup-bonus-loop`, `logic-approval-self`, `logic-cart-quantity-rounding`, `logic-invite-reuse`.
  - Chains: `chain-open-redirect-to-token-theft`, `chain-lfi-to-rce` (Insane), `chain-xss-to-csrf-admin`, `chain-jwt-to-sqli`, `chain-ssti-to-flask-config`.
  - Machines: `machine-saas-admin-console` (ORBIT) and `machine-hr-onboarding` (ATLAS HR), user/API/root flags with objective-gated root.
- **34 new exploit tests** (`tests/test_labs_phase3.py`) and **10 new platform tests** (`tests/test_platform_phase3.py`): active-lab cap, login throttling, path/catalog integrity, category coverage, achievements, profile export, accessibility, mobile CSS, search escaping.
- `run_tests.py`: runs every test module in its own interpreter.

### Fixed

- **Activity list leaked a `RV{` prefix:** masked submission values were rendered with the plaintext flag prefix. The list now shows only the masked value.
- **Achievements not returned on completion:** `award_completion` evaluated achievements but the response re-evaluated them and dropped the newly awarded ones; the completion path now returns them, and `evaluate_achievements` flushes each award so later conditions see it.
- **Notices in the pickle lab:** `server-deserialization-pickle` initially failed to surface the flag when a pickle gadget returned `bytes`. The notice renderer now coerces `bytes` and objects without `render()` safely, and the gadget used by the exploit test is builtins-only (`subprocess.check_output` / `eval`) so it does not depend on the lab's module name.
- **Test isolation:** a single `pytest` run reused the first module's `REDVAULT_DATA`, silently testing platform modules against another database. `run_tests.py` (and the `README`) now run one module per process.
- `labs/api-batch-endpoint-auth`: the singular `/api/admin/export` handler now accepts `POST` as well as `GET`.

### Changed

- Application version is now `0.8.0`.
- Learning paths include every new lab and machine; all 95 catalog items are listed in at least one path.
- Catalog status: **89 challenges + 8 machines**, 291 hints, 113 flags, 291 references (151 unique URLs), 57 objective-gated items, 4 Insane.

### Known gaps

- **Phase 3 missed its target:** 89 challenges (target 93) and 8 machines (target 9). Two planned machines (healthcare scheduling, e-commerce checkout) and 4 planned challenges were not built.
- 61 challenges and 7 machines remain to reach the 150/15 target.
- `bubblewrap` is a process sandbox, not a VM; labs retain host network egress.
- No database migration framework, TLS, MFA or multi-user isolation.

## [0.7.0] — 2026-11-12

### Added

- **27 new challenge labs** and **3 new machines** (61 catalog items total):
  - Recon: `recon-source-map`, `recon-cloud-listing`, `recon-api-docs`.
  - Authentication: `auth-session-fixation`, `auth-jwt-kid-traversal`, `auth-jwt-alg-confusion`, `auth-otp-bruteforce`.
  - Access control: `access-tenant-header`, `access-method-override`.
  - SQL injection: `sqli-blind-boolean`, `sqli-waf-bypass`.
  - XSS: `xss-attribute-injection`, `xss-blind-support`.
  - Server-side: `server-nosql-auth`, `server-blind-cmdi`, `server-xxe-reader`, `server-ssrf-webhook`.
  - API: `api-pagination-leak`.
  - Business logic: `logic-refund-abuse`, `logic-workflow-skip`.
  - Client-side: `client-cors-reflect`.
  - Upload: `upload-zip-slip`, `upload-filename-xss`.
  - Advanced: `adv-cache-poison-header`.
  - Insane chains: `chain-ssrf-internal`, `chain-upload-to-rce`, `chain-sqli-to-admin`.
  - Machines: `machine-fintech-support`, `machine-logistics-api`, `machine-insurance-claims` (user/API/root flags each).
- **27 new exploit tests**; the suite is now **61 lab tests + 13 platform tests = 74 tests**.
- Learning paths now include the new labs and the three new machines.

### Changed

- Application version is now `0.7.0`.
- `labs/_shared/serve_lab.py`: test/dev runner that imports a lab module and adds a header-preserving proxy, so filename-handling labs remain reproducible despite Werkzeug's multipart filename normalization.
- Catalog status: **55 challenges + 6 machines**, 3 Insane, 183 hints, 73 flags, 183 references (87 unique).

### Known gaps

- 104 catalog items remain to reach the 150 challenges + 15 machines minimum (95 challenges, 9 machines).
- `bubblewrap` is a process sandbox, not a VM; labs retain host network egress.
- No database migration framework, TLS, MFA or multi-user isolation.

## [0.6.0] — 2026-11-12

### Added

- **17 academy articles** in `content/academy/` covering methodology, recon, authentication, access control, SQL injection, XSS, SSRF, file inclusion, command injection, API security, JWT, business logic, client-side security, cache deception, file upload, chaining and a quick reference. Each article has YAML frontmatter, a table of contents, field notes and primary-source references.
- **13 platform integration tests** in `tests/test_platform.py` using an isolated temporary `REDVAULT_DATA` directory:
  - first-run validation and account creation
  - login/logout, redirect sanitization and CSRF
  - flag-value leakage checks across catalog and detail pages
  - CSRF enforcement on lab mutation
  - real lab start/status/reset/stop lifecycle
  - hint progression, penalties and solution gating
  - flag validation, completion, XP and duplicate handling
  - objective-gated flags
  - invalid internal callback tokens
  - primary UI page rendering
  - academy filters, articles and references
  - private profile export
  - confirmation-gated progress reset
- **Required documentation:** `README.md`, `INSTALL.md`, `ARCHITECTURE.md`, `SECURITY.md`, `ROADMAP.md`, this changelog.
- Explicit academy category filters for every implemented category, including `reference`.

### Fixed

- **Environments page crash:** `render()` received `active` both as the navigation key and as the active-lab list (`TypeError: render() got multiple values for argument 'active'`). The list is now passed as `active_labs` and the template uses that name.
- **Reset counter:** `LabManager.reset()` started a new `LabSession` without carrying the previous reset count. The new session now increments and persists `reset_count`.
- **Platform test isolation:** tests set `REDVAULT_DATA` before importing app modules so the real operator database, secret key and lab state are never touched.
- **Mobile overflow:** the tool library and CVE index could force Chrome's mobile layout viewport wider than 390 px because of long `<pre>` commands and an unwrapped table. Tool cards now use `minmax(0, 1fr)` tracks with constrained code blocks, and the CVE table scrolls inside its own container. All primary pages now render at exactly 390 px with no page-level horizontal overflow.
- **Stale version label:** the authentication footer still displayed `REDVAULT v0.5`; it now reads `v0.6`.

### Changed

- Application version is now `0.6.0`.
- Documentation states the actual catalog: **28 challenge labs, 3 machines, 31 working items**, not the 150/15 target.
- Test suite is now **44 tests** (31 lab exploit tests + 13 platform tests).

### Known gaps

- 122 challenge labs and 12 machines remain to reach the minimum target of 150 challenges and 15 machines.
- No `insane` difficulty lab exists yet.
- `bubblewrap` is a process sandbox, not a VM; labs retain host network egress.
- No database migration framework, TLS, MFA or multi-user isolation.

## [0.5.0] — baseline

### Added

- FastAPI + SQLite + Jinja2 + vanilla JS platform, loopback-only.
- First-run setup, bcrypt authentication, hashed sessions, CSRF, login throttling, security headers and CSP.
- Challenge and machine catalog, filters, search, detail pages, active lab controls and environments page.
- Lab process manager with port allocation, readiness checks, reset/stop, idle reaper, `bubblewrap` and `prlimit`.
- HMAC-derived per-lab flags, server-side validation and objective-gated callbacks.
- Progressive hints with XP penalties, solution gating and unlock history.
- XP, levels, achievements, notes, time tracking, activity feed and profile export.
- Ten learning paths, tool library, glossary and real CVE index.
- **31 real lab applications:** 28 challenges across all 12 categories and 3 machines with user/API/root flags.
- Selenium/Chromium loopback-only victim bot for XSS and client-side labs.
- 31 standalone exploit-level tests for every lab.

### Fixed

- `app/lab_manager.py` imported `sha256` from the wrong module.
- `labs/_shared/labkit.py` used an invalid f-string for the lab name.
- `bwrap` runtime now mounts shared code at `/shared` with `PYTHONPATH=/shared`.
- Native (non-bwrap) labs receive the real `LAB_STATE_DIR` rather than `/state`.
- `sqli-login-bypass` seed order now makes the tautology land on the administrator row.
- `sqli-second-order` now creates the missing `activity` table.
- `ssrf-image-fetcher` internal endpoint requires a proxy header, so direct loopback access returns 403; only the vulnerable fetcher adds it.
