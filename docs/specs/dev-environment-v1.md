# Spec — ambiente de desenvolvimento, qualidade e distribuição v1

- **Status:** aprovada pelo usuário em 2026-10-25; implementação concluída e validada em 2026-10-25.
- **Data:** 2026-10-25.
- **Prompt:** [`ai/prompts/06-quality-release.md`](../../ai/prompts/06-quality-release.md).
- **ADR:** [`docs/adr/0009-ambiente-de-desenvolvimento-build-e-release.md`](../adr/0009-ambiente-de-desenvolvimento-build-e-release.md).
- **Baseline:** branch `chore/dev-environment-release`, Python 3.15.0; ver seção Ambiente atual.
- **Escopo de hardware:** N/A. O incremento não altera protocolo, medição, calibração, unidades, thresholds, perfil, mapping, descoberta ou catálogo.

## Problema

O repositório ainda não descreve um ambiente completo reproduzível. O extra `dev` não instala `build` nem `pytest-cov`; a CI instala somente `.[dev]`, então os testes GUI podem ser pulados quando PySide6 está ausente; dependências transitivas não têm snapshot validado; README não conduz da criação do ambiente até build e instalação limpa; e os arquivos de distribuição não têm um critério de validação integrado.

## Usuário e contexto

Contribuidor em Linux com Python 3.15.0 configurado por asdf. A pessoa deve conseguir criar um ambiente local, executar CLI e GUI headless, rodar qualidade e produzir wheel/sdist sem instalar dependências de desenvolvimento no runtime do pacote.

## Resultado esperado

- `pyproject.toml` permanece a fonte única de dependências.
- `.[dev]` instala ferramentas de teste, cobertura, lint, tipos e build; `.[gui]` contém PySide6; `.[dev,gui]` é o ambiente completo de desenvolvimento.
- `constraints/dev.txt` registra uma resolução validada por pins exatos, incluindo dependências transitivas e ferramentas de build, sem a entrada editável do próprio ZonaPad.
- README fornece passos executáveis desde a toolchain até testes, build e smoke de wheel.
- CI executa testes GUI com PySide6 em `offscreen`, publica cobertura e valida instalação/build do pacote.
- Wheel e sdist são inspecionados por conteúdo e metadados; instalação limpa executa os smokes definidos.
- `CHANGELOG.md`, versão e receitas de distribuição têm estado explícito e verificável.

## Escopo

- Auditoria de imports e metadados de dependência.
- Extras `dev` e `gui`, constraints de desenvolvimento e política de atualização.
- Cobertura com `pytest-cov`, medição da baseline e publicação de `coverage.xml`.
- Workflow existente `.github/workflows/ai-assets.yml`, com jobs de check, test e package.
- Build isolado de wheel/sdist e inspeção de catálogo, entry points, metadados e licença.
- Instalação do wheel em ambiente descartável com e sem extra GUI e smoke de CLI/GUI.
- Seção README **Desenvolvimento**, troubleshooting, `CHANGELOG.md` e revisão de packaging AUR/Debian.
- Testes determinísticos de metadados, package data e imports de runtime.
- Atualização da fonte do Prompt 06 e índice de prompts para corrigir inconsistências identificadas durante o design.

## Fora de escopo

- Alteração de domínio, protocolo, medição, métricas, thresholds, calibração, wizard, mapping, descoberta, schema de perfil ou comportamento/mensagens da CLI/GUI.
- Publicação em PyPI, AUR ou Debian; assinatura de artefatos ou deploy.
- Mudança de versão do produto (permanece `0.1.0` neste incremento), novos entry points, plataforma Windows/macOS ou ferramentas adicionais fora da lista aprovada.
- Uso de hardware, `/dev/input`, `/dev/uinput` ou display real.
- Mudança no nome do workflow ou inclusão de serviço externo de cobertura.

## Requisitos funcionais

### Dependências e imports

1. `project.dependencies` permanece vazio; runtime importa apenas stdlib e módulos internos.
2. O extra `gui` mantém `PySide6>=6.7` como única dependência de aplicação opcional.
3. O extra `dev` passa a incluir `pytest`, `pytest-cov`, `ruff`, `mypy`, `virtualenv` e `build`. Mantém floors atuais de pytest, Ruff, mypy e virtualenv; os floors iniciais de pytest-cov/build serão as versões efetivamente testadas na implementação, registradas no pyproject e ADR.
4. Imports de PySide6 permanecem sob `interface/gui/`; módulos runtime fora dessa árvore não importam ferramentas de desenvolvimento.
5. `pip check` retorna código 0 no ambiente completo e no ambiente instalado a partir do wheel.

### Ambiente e constraints

1. README explica Python/asdf 3.15.0, criação com `virtualenv` e alternativa com `venv`, instalação de `.[dev]` e `.[dev,gui]`, comandos de qualidade e seus resultados esperados.
2. `constraints/dev.txt` contém pins `==` para a resolução completa aprovada, incluindo PySide6 e dependências de build usadas na validação. Pins de backend/build isolation, como setuptools, são declarados explicitamente na constraint mesmo quando `pip freeze` do ambiente principal não os captura.
3. O arquivo não declara extras nem substitui `pyproject.toml`; exclui a distribuição editável `zonepad` e pacotes alheios ao ambiente.
4. CI instala com `PIP_CONSTRAINT=constraints/dev.txt`. README documenta atualização: instalar extras sem constraint, rodar suíte e `pip check`, gerar `pip freeze`, remover a linha editável/projeto e itens alheios, revisar o diff e obter revisão antes de atualizar os pins.
5. A faixa `>=` do metadata continua permitindo resolução compatível a consumidores do wheel; constraints são política de desenvolvimento/CI.

### Testes, cobertura e CI

1. `pytest-cov` habilita cobertura de `zonepad`, relatório terminal com linhas faltantes e `coverage.xml`.
2. A cobertura de linhas baseline é medida e registrada no ADR. Neste incremento não se define `fail_under`: o relatório é publicado como evidência e um limite futuro requer alvo justificado e nova decisão. A configuração padrão não mede branches.
3. Job `check` preserva Ruff, mypy e `sync_ai_assets.py --check`.
4. Job `test` instala o runtime Qt `libegl1`, instala `.[dev,gui]` com constraints, configura `QT_QPA_PLATFORM=offscreen`, verifica `import PySide6`, executa a suíte e `tests/test_gui.py` explicitamente com JUnit XML; uma verificação com `xml.etree.ElementTree` falha se houver caso skipped no resultado dedicado; executa `pip check` e publica `coverage.xml`.
5. Job `package` instala `libegl1`, constrói sdist/wheel, inspeciona conteúdo, instala o wheel em venv descartável sem GUI e roda CLI/diagnóstico da GUI ausente; em seguida instala o extra GUI, roda `zonepad-gui --smoke` offscreen, executa `pip check` e publica `dist/*` como artefato.
6. Workflow mantém Python 3.15.0, nome `ai-assets` e inclui README, constraints, packaging e pyproject nos gatilhos de paths.

### Build e instalação limpa

1. `python -m build` usa o isolamento padrão do backend e gera `zonepad-0.1.0-py3-none-any.whl` e `zonepad-0.1.0.tar.gz`.
2. Wheel inclui o pacote Python completo, `catalog_data/families.json`, entry points `zonepad` e `zonepad-gui`, `Requires-Python`, metadados dos extras e descrição longa derivada do README.
3. O METADATA lista os arquivos de licença; cada caminho `License-File` existe em `.dist-info/licenses/` no wheel. O sdist inclui `pyproject.toml`, `src/zonepad/`, README, LICENSE e `constraints/dev.txt`. Se o setuptools não incluir constraints automaticamente, `MANIFEST.in` declara sua inclusão; esse arquivo orienta conteúdo de source archive e não duplica dependências.
4. Em venv limpo sem GUI, `zonepad --help` e `zonepad devices --help` retornam 0; `zonepad-gui` retorna 2 com instrução acionável, sem traceback.
5. Após instalar o wheel com extra GUI, `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke` retorna 0. Nenhum smoke inicia discovery ou abre dispositivos.

### Changelog e distribuição

1. `CHANGELOG.md` segue Keep a Changelog em PT-BR, com `[Não publicado]` e `[0.1.0]`, resumindo os incrementos 00–05.
2. A versão do projeto fica em `pyproject.toml` e coincide com `pkgver` do PKGBUILD.
3. PKGBUILD mantém instalação via wheel local, `python-build`/`python-installer` em `makedepends` e informa `pyside6` como dependência opcional para GUI.
4. Debian permanece scaffold nesta versão: `packaging/debian/README.source` será atualizado para declarar que as regras atuais não constituem pacote Debian validado e que ainda não há `debian/changelog` nem versão Debian. `control` registra GUI como sugestão opcional. A conversão completa para pybuild e validação em distribuição com Python 3.15 exige incremento próprio ou ampliação aprovada.

## Requisitos não funcionais

- Testes e smokes são determinísticos, sem rede além do PyPI padrão para instalação/build, sem hardware e sem display real.
- A instalação limpa usa diretório ignorado `dist/smoke-venv`; artefatos locais de build/cobertura permanecem fora do controle de versão.
- Nenhum pacote de ferramenta de desenvolvimento entra em `project.dependencies`.
- Atualização de pins falha explicitamente quando uma resolução não está disponível; CI não substitui o índice configurado silenciosamente.
- A CI usa jobs separados e cache de pip com chave que inclui Python, pyproject e constraints.

## Modelo de dados e unidades

Não há dados de controle, units, frames ou perfis alterados. O modelo desta feature é metadata de distribuição e ambiente:

| Artefato | Unidade/representação | Fonte | Uso |
|---|---|---|---|
| Versão de pacote | PEP 440, string `0.1.0` | `pyproject.toml` | wheel, sdist, changelog e AUR |
| Pin de dependência | versão exata `==` | resolução validada | ambiente local/CI |
| Cobertura | percentual de linhas executáveis conforme pytest-cov | execução da suíte | baseline e artefato CI; sem threshold neste incremento |
| Arquivo de pacote | caminho relativo dentro do archive | wheel/sdist | conteúdo e entry points verificáveis |

## Impacto por camada

- **Domain/Application:** nenhum arquivo ou contrato alterado.
- **Infrastructure/Interface:** nenhuma regra de execução alterada; PySide6 continua opcional e importado na GUI.
- **Packaging:** metadados, extras, constraints, build, AUR/Debian e instalação limpa.
- **CI:** instalação completa de GUI e ferramentas, testes/cobertura, package smoke e artefatos.
- **Docs/AI:** README, changelog, spec, ADR e consistência do Prompt 06/índice.

## Impacto em hardware/dispositivos

N/A, confirmado pelo escopo: nenhum protocolo, leitura, semântica, métrica, calibração, perfil ou suporte a dispositivo muda. Testes usam fixtures/fakes e a GUI executa somente `--smoke` em `offscreen`, sem discovery.

## Plano de testes

| Camada | Caso | Critério |
|---|---|---|
| Metadados | extras, runtime deps, versão, entry points | `tests/test_packaging.py` valida pyproject sem build/rede |
| Package data | arquivos JSON em catalog_data versus padrão declarado | todo JSON da árvore é coberto e famílias está no pacote |
| Imports | AST do runtime fora de GUI | nenhum import de PySide6 ou ferramenta dev |
| Baseline | suíte atual e GUI em offscreen | 704 pass + 5 subtests iniciais; após implementação, 709 pass + 5 subtests e 11 testes GUI sem skips |
| Cobertura | suíte total com pytest-cov | 83% de linhas, 7.152 statements e 1.200 misses; coverage.xml gerado; sem fail_under |
| Dependências | `pip check` no dev e smoke venv | sem dependências quebradas |
| CI GUI | ambiente `.[dev,gui]` | PySide6 importável, teste dedicado concluído, skip count 0 |
| Build | wheel e sdist | nomes, entry points, catálogo, metadados, licença e README conferidos |
| Smoke sem GUI | wheel em venv novo | CLI help 0, device help 0, GUI ausente retorna 2 sem traceback |
| Smoke com GUI | instalar wheel extra `[gui]` | `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke` retorna 0 |
| Regressão | suíte completa após mudanças | todas as anteriores permanecem verdes e novos testes passam |

## Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Pins desatualizados | instalação/CI deixa de resolver ou bloqueia correção | procedimento de atualização com suíte verde, `pip check` e revisão do diff |
| PySide6 sem wheel para Python 3.15 | job GUI e instalação completa falham | pin validado, import explícito e erro de CI claro |
| Baseline de cobertura sem alvo | percentagem pode virar gate arbitrário | publicar medida, registrar no ADR e manter fail_under ausente |
| Build backend em isolamento | resolução de setuptools diverge | incluir versões de build na constraint e validar CI/build local |
| Wheel omite catálogo/licença/entry points | instalação falha em runtime | inspeção por conteúdo e teste de metadados |
| Instalação limpa requer PyPI | indisponibilidade externa bloqueia smoke | registrar falha de rede, usar somente cache/artefato PyPI padrão documentado |
| Debian depende de Python 3.15 | scaffold pode não ser instalável em distribuição atual | declarar scaffold e não anunciar suporte/versão validada |
| README diverge dos comandos | onboarding falha | revisão de prompt + execução literal dos passos em ambiente limpo |

## Critérios de aceite

- [ ] `dependencies == []`; PySide6 permanece somente em `gui`.
- [ ] `dev` instala pytest, pytest-cov, ruff, mypy, virtualenv e build.
- [ ] Constraints são pins exatos da resolução verde, incluem dependências de build, excluem ZonaPad editável e são aplicadas pela CI.
- [ ] Política de atualização de constraints tem comandos e revisão documentados.
- [ ] Baseline de cobertura é medida, registrada no ADR e publicada; decisão de não definir fail_under é explícita.
- [ ] CI executa os 11 testes GUI sem skips em `offscreen`, cobertura, `pip check`, build e smokes.
- [ ] Wheel/sdist contêm os caminhos/metadados definidos e validáveis por listagem.
- [ ] Venv limpo sem GUI e com GUI passa os três smokes definidos e `pip check`.
- [ ] README contém a seção Desenvolvimento com setup, extras, qualidade, cobertura, build, instalação limpa, troubleshooting, origem das dependências e matriz CI.
- [ ] `CHANGELOG.md` lista `[Não publicado]` e `[0.1.0]`; versão e AUR estão alinhados.
- [ ] Debian continua identificado como scaffold, com sugestão opcional GUI e sem alegação de versão/build validado.
- [ ] `packaging/debian/README.source` declara o estado scaffold, a ausência de changelog/versão e a necessidade de validação numa distro com Python 3.15.
- [ ] Testes de packaging são determinísticos, sem rede nem build.
- [ ] Nenhum arquivo domain/application de medição/calibração/schema é alterado.
- [ ] `controller-hardware` é registrado como N/A com justificativa.

## Decisões D1–D12

| ID | Decisão proposta | Responsável | Justificativa observada |
|---|---|---|---|
| D1 | `pyproject.toml` é a única fonte de dependências; runtime mantém `dependencies = []`. | Python | Configuração atual já separa runtime e extras; nenhum runtime externo é importado. |
| D2 | `constraints/dev.txt` usa pins exatos do ambiente aprovado, incluindo backend/build isolation; `>=` permanece no metadata de consumidor. | Python + usuário | `pip freeze` atual não inclui o setuptools isolado, então backend pins serão declarados explicitamente. |
| D3 | `dev` adiciona pytest-cov e build às ferramentas existentes; `gui` mantém apenas PySide6. Floors novos refletem versões efetivamente testadas. | Python | Baseline confirmou pytest 9.1.1, Ruff 0.17.2, mypy 2.4.0, virtualenv 21.14.13 e PySide6 6.12.0; build/cov ainda não instalados. |
| D4 | `virtualenv` é o caminho documentado principal, com bootstrap via pipx; `venv` é alternativa e runtime não depende de virtualenv. | Python | README já usa virtualenv; Python inclui `venv` e o usuário pode escolher o caminho alternativo. |
| D5 | Ferramentas limitadas a pytest, pytest-cov, Ruff, mypy, build, virtualenv e pip check. | Python | Cada ferramenta corresponde a um gate ou comando de onboarding especificado. |
| D6 | Medir cobertura de linhas, publicar XML e registrar valor; não definir `fail_under` neste incremento. | Python + usuário | Ainda não há cobertura medida nem alvo acordado que justifique limite de bloqueio. |
| D7 | CI instala `.[dev,gui]`, usa offscreen, importa PySide6 e verifica zero skips via JUnit XML + stdlib. | Python | `pytest.importorskip` pode pular a GUI; import e contagem explícita tornam essa falha visível. |
| D8 | `python -m build` isolado gera wheel/sdist; conteúdo é verificado por arquivo e METADATA; MANIFEST.in inclui constraints se necessário. | Python | setuptools precisa preservar catálogo, entry points, descrição/license metadata e constraints no sdist. |
| D9 | Job package usa venv descartável para smoke sem GUI e com extra GUI, depois publica artefato de CI. | Python | CLI independente e GUI opcional precisam ser provadas no wheel instalado. |
| D10 | AUR declara `pyside6` como optdepend; Debian permanece scaffold com `Suggests` e aviso explícito de não validação/sem versão. | Python + usuário | Arquivos Debian atuais dizem scaffold, não têm changelog e não foram validados com uma distro que forneça Python 3.15. |
| D11 | Manter versão 0.1.0 e criar changelog Keep a Changelog em PT-BR; Debian scaffold permanece sem versão. | Python | `pyproject.toml` e PKGBUILD já declaram 0.1.0; nenhuma publicação ocorreu. |
| D12 | Nenhuma publicação, mudança de runtime/domínio/GUI, suporte de hardware ou ferramenta extra. | Principal | O incremento fecha qualidade/packaging e mantém limites do MVP. |

## Decisões pendentes

- Aprovação do usuário para esta spec e ADR 0009 antes de editar pyproject, constraints, CI, README de produto ou packaging.
- Durante a implementação: registrar número de cobertura obtido e versões exatas instaladas; manter decisão sem `fail_under` conforme D6.

