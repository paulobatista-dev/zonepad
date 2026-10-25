# Prompt 04 — Descoberta de dispositivos e mapeamento por família

- **Status:** pronto para execução em Claude Code (prioritária) e Codex (alternativa).
- **Incremento:** descoberta de gamepads Linux via sysfs/evdev, identidade estável, capabilities, catálogo por família, mapping draft v1, CLI `devices`/`mapping`, hot-plug por polling e integração com `run`/`calibrate`.
- **Branch de implementação:** `feat/device-discovery-mapping`, criada a partir da `main` com este prompt mergeado.
- **Fluxos:** `/flow-design-feature` → `/flow-implement-feature` → `/flow-review-calibration`.
- **Agentes:** `controller-hardware` (identidade, filtro, capabilities, catálogo, hot-plug, números), `python-engineer` (adapters, registry, mapping, watcher, CLI, testes, docs), `prompt-engineer` (apenas `ai/` e consistência) e Claude/Codex principal (orquestração, handoffs, síntese).
- **Fora deste incremento:** GUI (prompt 05), qualidade/release (prompt 06), Windows/macOS, schema de perfil v2, fórmulas de métricas, emulação, firmware/kernel, push/PR/merge.

## Missão

Eliminar a seleção manual por `eventN` e o mapping escrito à mão. Ao final, a pessoa escreve:

```bash
zonepad devices
zonepad mapping draft --device usb-045e-02ea-<serial>
zonepad calibrate --device usb-045e-02ea-<serial>
zonepad run --device usb-045e-02ea-<serial> --profile <uuid>
```

O sistema descobre apenas gamepads, identifica cada controle por uma chave estável, lê capabilities e ranges do sysfs, gera um mapping `schema_version=1` a partir de um catálogo por família com overrides, persiste por identidade e resolve esse mapping automaticamente. `eventN` continua aceito durante a transição e `--mapping` explícito continua vencendo tudo.

O mapping gerado é **draft**: usa ranges reais do dispositivo, mas centro e repouso declarados são provisórios até o wizard medir. O incremento não recalcula métricas, não altera thresholds e não muda o schema do perfil.

## Resultado esperado

1. Descoberta Linux lendo `/sys/class/input/event*` e resolvendo symlinks, sem abrir o nó do dispositivo.
2. Filtro de gamepads com critérios declarados por capabilities, excluindo teclado, mouse, touchpad e devices virtuais conhecidos.
3. Identidade estável (`vid`, `pid`, `uniq`, `phys`, nome, índice de desambiguação) que nunca depende de `eventN`.
4. Modelo de capabilities (eixos com `minimum`/`maximum`/`flat`/`fuzz`/`resolution`, botões, tipos de evento, propriedades).
5. Catálogo declarativo por família, com override explícito e fallback genérico honesto.
6. Geração, validação e persistência de mapping v1 por identidade + conexão, sem tocar no schema v1 existente.
7. CLI `zonepad devices` e `zonepad mapping {draft,show,validate}` com saída legível, `--json` e exit codes documentados.
8. `run` e `calibrate` aceitando ID estável e resolvendo o mapping salvo, mantendo `eventN` e `--mapping` explícito.
9. Watcher de hot-plug por polling com relógio injetado, sem root e sem dependência nova.
10. `docs/specs/device-discovery-v1.md`, `docs/adr/0006-*.md`, README e testes determinísticos sem hardware.

## Contexto verificado (2026-10-25, `main` em `7084dc2`)

Revalide no checkout principal com working tree limpo. Os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado |
| --- | --- |
| `zonepad list` | `src/zonepad/interface/cli.py:60` e `:179-190` imprimem `id`, `name` e `capabilities` em JSON por linha |
| Backend evdev | `src/zonepad/infrastructure/evdev.py:131-137` lista todo `event*` sem filtro e sem `vendor_id`/`product_id` |
| Abertura | `evdev.py:139-151` só aceita `event[0-9]+` (`:142`) e exige `mapping` no construtor (`:120-129`) |
| Identidade | `src/zonepad/domain/device.py:7-31` define `DeviceInfo` com `vendor_id`, `product_id`, `guid`, `serial`; não há `uniq` nem `phys` |
| Mapping v1 | `src/zonepad/infrastructure/mapping.py:13-15` fixa `lx,ly,rx,ry`, `lt,rt` e quatro botões faciais; `:66` exige `schema_version=1`; `:169` rejeita campos desconhecidos |
| Runtime | `cli.py:65-74` e `:278-284`: `--device` e `--profile` obrigatórios, `--mapping` obrigatório na execução |
| Wizard | `cli.py:107-172` e `:208-209`: `--mapping` obrigatório; `--device` opcional com seleção manual |
| Portas | `src/zonepad/application/ports.py:25-30` `DeviceBackend.list_devices`/`open`; `:11-23` `DeviceSession` |
| VID/PID hoje | ADR `0005-wizard-cli-calibrate.md` item 8: o backend atual não expõe VID/PID e `0x0000` significa desconhecido |
| sysfs | sem uso em `src/`; nenhuma leitura de `/sys/class/input` hoje |
| Testes | `tests/` usa `pytest`, fakes e `tmp_path`; nenhum hardware; `tests/synthetic_capture.py` gera capturas |

Leia antes de editar: `AGENTS.md`, `docs/specs/metrics-v1.md`, `docs/specs/wizard-v1.md`, `docs/adr/0003-*.md`, `docs/adr/0004-*.md`, `docs/adr/0005-*.md`, `src/zonepad/domain/device.py`, `src/zonepad/application/ports.py`, `src/zonepad/infrastructure/evdev.py`, `src/zonepad/infrastructure/mapping.py`, `src/zonepad/interface/cli.py`, `src/zonepad/interface/calibration_cli.py` e `tests/`.

Skills aplicáveis: `controller-protocols`, `calibration-domain`, `python-app-architecture`, `clean-architecture`, `clean-code`, `python-quality`, `evidence-based`.

## Pré-condições

1. Este prompt deve estar mergeado em `main`. Enquanto não estiver, execute no checkout principal a partir da branch que contém o prompt e registre a exceção.
2. Trabalhe **somente no checkout principal**. É proibido `git worktree`, cópia do repo para outro diretório e edição de arquivos gerados (`AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`).
3. Crie a branch de implementação a partir da `main`:

```bash
cd /home/costa/Workspace/zonepad
git status --porcelain        # deve estar vazio
git switch main
git pull --ff-only
git switch -c feat/device-discovery-mapping
```

4. Toolchain e baseline:

```bash
asdf current python        # 3.15.0; se não, pare e reporte
python --version           # Python 3.15.0
python -m venv .venv       # ou: virtualenv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q        # baseline verde antes de editar
```

5. Gates de entrada:

```bash
git status --porcelain        # vazio
git branch --show-current     # feat/device-discovery-mapping
git log --oneline main..HEAD  # vazio no início
```

Se qualquer gate falhar, pare e peça um checkout principal limpo.

6. Regras de git e segurança:

- Commit local é permitido; push, PR, merge e rebase só com pedido explícito do usuário.
- Proibido `git stash`, `git reset`, `git checkout --`, `git restore`, `git rebase`, `git push --force` e `sudo`.
- Não acesse hardware real, `/dev/input` ou `/dev/uinput` sem confirmação explícita; a CI e os testes usam fixtures e fakes.
- Não introduza dependência nova sem aprovação do usuário e registro na spec.

## Agentes

| Agente | Executa | Não executa |
| --- | --- | --- |
| `controller-hardware` | Define a identidade estável e sua hierarquia de campos, os critérios de filtro de gamepad, a leitura de capabilities evdev/sysfs (`id/*`, `uniq`, `phys`, `capabilities/abs`, `capabilities/key`, `capabilities/ev`, `properties`), o catálogo e os overrides por família, o modelo de hot-plug e a revisão dos números do smoke. Assina o parecer de hardware. | Não implementa código de produção; não edita `src/`, `tests/` ou CLI; não altera prompts/skills; não decide estrutura de módulos nem packaging. |
| `python-engineer` | Implementa os adapters de sysfs e evdev, o modelo de identidade/capabilities, o registry e a persistência, o gerador de mapping draft, o watcher de hot-plug, a integração com `run`/`calibrate`, a CLI `devices`/`mapping`, a validação de schema e os testes; escreve README e documentação técnica. | Não define critérios de filtro, hierarquia de identidade, ranges esperados, catálogo por família nem política de hot-plug; não altera fórmulas, thresholds, schema de perfil ou `measure`. |
| `prompt-engineer` | Atua apenas em `ai/` (prompts, skills, fluxos, `AGENTS.md`) e na revisão de consistência entre prompt, README, spec e agentes; reporta contradições. | Não implementa descoberta, identidade, mapping, watcher ou CLI; não assina critério de hardware nem de arquitetura. |
| Claude/Codex principal | Orquestra design → implementação → revisão, faz handoffs com contexto, resolve conflitos, cobra gates, valida a spec com o usuário e sintetiza o relatório final. | Não substitui o parecer de `controller-hardware`; não inventa critério de filtro, campo de identidade ou família; não autoriza push/PR/merge. |

Aprovação humana (usuário): aprova `docs/specs/device-discovery-v1.md` **antes** de qualquer código de produção, autoriza dependência nova ou acesso a hardware e autoriza push/PR/merge.

Handoff mínimo: objetivo, contexto verificado, restrições, arquivos relevantes, saída esperada e critério de aceite. Em Claude Code, use a ferramenta **Agent** com o nome do subagente. Em Codex, use subagente ou siga o `FLOW.md` correspondente.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight, branch e baseline | `python-engineer` | principal | `/flow-implement-feature` (1–2) | branch `feat/device-discovery-mapping`, baseline pytest | tree limpo; 3.15.0; pytest verde |
| 2 | Identidade, filtro de gamepad e leitura de capabilities | `controller-hardware` | principal | `/flow-design-feature` + `controller-protocols` | seção de hardware da spec | hierarquia de identidade e critérios de filtro explícitos |
| 3 | Catálogo por família, ranges e centro/repouso provisórios | `controller-hardware` | `python-engineer` | `/flow-design-feature` + `calibration-domain` | catálogo declarativo + regras de override | draft honesto: nada apresentado como calibrado |
| 4 | Contratos, portas, persistência e compatibilidade | `python-engineer` | `controller-hardware`, `prompt-engineer` | `/flow-design-feature` + `python-app-architecture` | spec de arquitetura + ADR 0006 | precedência de mapping e compat `eventN` fechadas |
| 5 | **Aprovação da spec pelo usuário** | principal | usuário | — | spec aprovada | sem aprovação, não há implementação |
| 6 | Domínio: identidade, capabilities, mapping draft | `python-engineer` | `controller-hardware` (semântica) | `/flow-implement-feature` (3) + `clean-architecture` | tipos puros + testes de borda | `domain/` sem `os`, `pathlib`, `evdev`, `time` |
| 7 | Adapter sysfs + fixtures | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (5) | `infrastructure/sysfs.py` + fixtures | raiz sysfs injetável; nenhum `/sys` real |
| 8 | Registry, mapping draft e persistência | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (5) + `python-quality` | store + validação via `load_device_mapping` | mapping salvo passa no parser v1 sem campos novos |
| 9 | CLI `devices` e `mapping` | `python-engineer` | principal | `/flow-implement-feature` (6) | subcomandos + help | `--help` completo; exit codes documentados |
| 10 | Integração `run`/`calibrate` | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (4–6) | resolução de ID estável | `eventN` e `--mapping` continuam funcionando |
| 11 | Watcher de hot-plug | `python-engineer` | `controller-hardware` | `/flow-implement-feature` (5) | watcher + fake de relógio | sem root, sem dependência nova, determinístico |
| 12 | Testes e validação | `python-engineer` | `controller-hardware` (fixtures) | `python-quality` | suíte nova em `tests/` | matriz da seção "Testes obrigatórios" verde |
| 13 | Smoke com hardware (se houver e com autorização) | `controller-hardware` conduz; `python-engineer` apoia | principal | `/flow-implement-feature` (7) | saída de `devices`, mapping, parecer | VID/PID, ranges e botões plausíveis; falhas declaradas |
| 14 | README, spec, ADR e `ai/` | `python-engineer` (README/ADR) + `prompt-engineer` (`ai/`) | principal | `python-quality`, `prompt-design` | docs e status do prompt 04 | `sync --check` limpo se `ai/` mudou |
| 15 | Revisão final | `controller-hardware`, `python-engineer`, `prompt-engineer` | principal sintetiza | `/flow-review-calibration` | relatório com severidade e arquivo:linha | nenhum bloqueador |
| 16 | Encerramento | principal | usuário | — | entrega no formato de saída | critérios marcados; riscos e handoff registrados |

`controller-hardware` é obrigatório nas etapas 2, 3, 6 (revisão de semântica), 7, 10 (revisão), 11, 13 e 15. Sem esse parecer, o incremento não está pronto.

## Decisões que a spec deve fechar

Cada decisão tem dono. `controller-hardware` decide hardware e semântica; `python-engineer` decide estrutura e artefatos. Mudança de recomendação exige justificativa registrada na spec.

| ID | Decisão | Recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | Fonte de verdade da descoberta | Sysfs `/sys/class/input` como fonte primária (`name`, `id/vendor`, `id/product`, `id/version`, `uniq`, `phys`, `capabilities/*`, `properties`), sem abrir o nó; `EVIOCG*` só como confirmação opcional atrás de porta | `controller-hardware` |
| D2 | Filtro de gamepad | Exigir `EV_ABS` com `ABS_X` e `ABS_Y` **e** `EV_KEY` com ao menos um botão de gamepad (`BTN_SOUTH`/`BTN_GAMEPAD`/`BTN_JOYSTICK`); excluir `KEY_A`/`KEY_SPACE` (teclado), qualquer `REL_*` (mouse), `INPUT_PROP_POINTER` e `ABS_MT_*` (touchpad); classificar o resto como `unknown` e mostrar só com `--all` | `controller-hardware` |
| D3 | Hierarquia de identidade | `uniq` (serial do firmware) > `phys` (caminho da porta USB) > `serial` > índice de ocorrência; `eventN` nunca entra na identidade persistida | `controller-hardware` |
| D4 | Formato do ID estável | Slug legível e estável em arquivo: `<bus>-<vid>-<pid>-<qualificador>`, sanitizado, com sufixo `-2`, `-3` para duplicados; hash curto apenas se o slug estourar limite ou contiver caracteres não suportados | `python-engineer` |
| D5 | Duplicados idênticos | Mesmo `vid`/`pid`/`uniq`/`phys` ausente → sufixo determinístico pela ordem numérica de `eventN`, aviso explícito de fragilidade e confirmação obrigatória ao salvar mapping | `controller-hardware` |
| D6 | Chave de persistência | (identidade, conexão `usb`/`bluetooth`/`desconhecida`, firmware quando exposto); sem fallback silencioso entre chaves; `--connection` permite override | `python-engineer` |
| D7 | Onde mora o mapping | Arquivo v1 **inalterado** (o parser rejeita campos desconhecidos em `mapping.py:169`) + sidecar de identidade/proveniência; nunca adicionar `device`/`firmware` ao schema v1 | `python-engineer` |
| D8 | Precedência de mapping | `--mapping` explícito > mapping salvo da identidade > erro acionável; nunca usar mapping de outra identidade, nem de uma conexão diferente da atual | `python-engineer` |
| D9 | Centro e repouso do draft | `minimum`/`maximum` de `capabilities/abs`; `center` = override de catálogo ou midpoint provisório; `rest` de trigger = mínimo do absinfo; marcar `provisional=true` na proveniência e avisar que a calibração corrige | `controller-hardware` |
| D10 | Catálogo por família | Tabela declarativa versionada por `vid:pid` e nome, com overrides de código/range; família desconhecida gera draft genérico com aviso, nunca erro fatal | `controller-hardware` |
| D11 | Hot-plug | Polling com intervalo injetado (padrão 1 s) e comparação de snapshots; udev/netlink só se a spec justificar e o usuário aprovar dependência; reconexão do runtime explicitamente fora | `python-engineer` |
| D12 | Compatibilidade `eventN` | `eventN` resolve para identidade na entrada; `--mapping` explícito mantém precedência; `zonepad list` inalterado; `devices` é o comando novo | `python-engineer` |
| D13 | Permissões | Ler sysfs sem privilégio; abrir o nó exige grupo `input`; mensagem acionável, nunca `sudo` automático nem alteração de permissões | `controller-hardware` |
| D14 | Testabilidade | Raiz sysfs injetável, watcher e relógio injetados, fixtures em `tmp_path`; nenhum `/sys`, `/dev/input` ou `sleep` real na CI | `python-engineer` |

## Escopo

### 1. Descoberta via sysfs

- Porta de leitura injetável com raiz configurável (`sysfs_root: Path = /sys/class/input`). Toda leitura passa por ela; o adapter é o único módulo que toca o sistema de arquivos real.
- Para cada `event*`: ler `dev`, `name`, `device/id/vendor`, `device/id/product`, `device/id/version`, `device/id/bustype`, `device/uniq`, `device/phys`, `device/capabilities/{ev,key,abs,rel,msc,sw}`, `device/properties` e `device/uevent` quando existir.
- Resolver o symlink `device` com `Path.resolve()`; registrar `sysfs_path` apenas para diagnóstico, nunca como identidade.
- Um `event*` sem `device` resolvível, sem `name` legível ou com erro de permissão vira candidato `unknown` com motivo, sem abortar a descoberta inteira.
- Nenhum `open()` em `/dev/input/event*` durante `devices` ou `mapping draft`; `run`/`calibrate` continuam abrindo o nó.
- Ordenar a saída por identidade estável, não por `eventN`, para que a listagem seja estável entre boots.

### 2. Identidade estável

- Tipo imutável no domínio com `stable_id`, `vid`, `pid`, `version`, `bustype`, `name`, `uniq`, `phys`, `occurrence`, `connection`, `firmware` (opcional) e `event_node` como dado volátil explicitamente marcado.
- `event_node` nunca é persistido como chave; serve apenas para abrir a sessão na execução atual.
- `connection` derivada de `bustype`/`phys` (`usb`, `bluetooth`, `desconhecida`); `firmware` só quando exposta pelo device, com `None` explícito quando ausente.
- Duplicados: sufixo determinístico e aviso; documentar que o índice pode mudar se o usuário trocar a porta ou reconectar na mesma porta em ordem diferente.
- Estender `DeviceInfo` ou introduzir um tipo próprio; se estender, ajuste construtores existentes e `evdev.py` sem quebrar `list`, `run` e `calibrate`.

### 3. Capabilities

- Modelo de domínio: `AxisCapability(code, minimum, maximum, flat, fuzz, resolution)`, `ButtonCapability(code)`, tipos de evento presentes, propriedades do device e canal semântico sugerido (`lx`, `ly`, `rx`, `ry`, `lt`, `rt`) quando reconhecido.
- Interpretar `capabilities/abs` no formato do kernel (`<code_hex>:<min>:<max>:<flat>:<fuzz>:<resolution>` por linha) e `capabilities/key`/`ev` como máscaras hexadecimais de 64 bits por palavra.
- Validar consistência: `minimum < maximum`, código dentro de `0x00-0x3f` para `ABS_*` e `0x000-0x2ff` para `BTN_*`/`KEY_*`, ausência de duplicatas.
- Não presumir ranges: nada de `-32768..32767` fixo. Dispositivo sem `ABS_Z`/`ABS_RZ` e sem botão de trigger gera draft parcial com aviso e exit code próprio na CLI.
- Não inferir centro calibrado a partir de absinfo; o centro do draft é provisório (D9).

### 4. Catálogo por família

- Catálogo declarativo, versionado, legível, dentro do repositório (por exemplo `src/zonepad/infrastructure/catalog/*.json` ou tabela em módulo), indexado por `vid:pid` com nome/aliases.
- Cada entrada pode definir: nomes/códigos esperados de eixos e triggers, mapeamento de botões faciais, ranges conhecidos, conexão esperada e observações de quirk.
- Precedência: override explícito do usuário > catálogo da família > heurística genérica por capabilities.
- Família desconhecida: draft genérico + aviso "família não catalogada; valide com `zonepad calibrate`".
- Catálogo não pode ser usado como fonte de ranges quando o dispositivo expõe absinfo diferente; o absinfo vence e a divergência é registrada como aviso.

### 5. Mapping draft e persistência

- Gerar `DeviceMapping` v1 completa (`lx`, `ly`, `rx`, `ry`, `lt`, `rt` e até quatro botões faciais) e validar com `load_device_mapping` antes de gravar.
- Nunca gravar mapping parcial: se faltar canal essencial, falhe com mensagem que liste os canais ausentes e o que foi detectado.
- Layout proposto: `~/.config/zonepad/devices/<stable_id>/mapping.json` (v1 intacto) + `<stable_id>/identity.json` (identidade, conexão, firmware, versão do catálogo, data, `provisional`, `sha256` do mapping, origem).
- Gravação atômica (`write_text_atomic` existente), UTF-8, `allow_nan=False`; recusa sobrescrever sem `--force`; `--print` grava só em stdout.
- Registry: índice legível (`~/.config/zonepad/devices/index.json`) com uma entrada por chave de D6, para listar mappings e detectar duplicatas sem varrer diretórios.
- Validação de leitura: mapping importado ou salvo passa por `load_device_mapping`; arquivo inválido reporta o campo e não derruba os demais.
- `mapping_sha256` continua sendo o hash do arquivo de mapping usado, para manter a rastreabilidade de `measure`/`calibrate`.

### 6. CLI `zonepad devices`

```bash
zonepad devices [--json] [--all] [--verify] [--sysfs-root PATH]
```

- Padrão: tabela legível em PT-BR com `ID`, `NOME`, `VID:PID`, `CONEXÃO`, `NÓ`, `MAPPING` (`salvo`/`ausente`/`provisório`).
- `--json`: uma linha JSON por dispositivo, campos estáveis, ordenados por ID.
- `--all`: inclui candidatos `unknown`/não-gamepad com coluna de motivo.
- `--verify`: tenta abrir cada nó para confirmar acesso de leitura e informa permissão; exige autorização e nunca é padrão.
- `--sysfs-root`: raiz alternativa, útil para testes e smoke com fixtures.
- Exit codes: `0` ao menos um gamepad; `3` nenhum gamepad, sysfs ausente ou `/sys` inacessível; `2` argumentos inválidos; `1` falha inesperada.
- `zonepad list` permanece inalterado neste incremento; README passa a recomendar `devices`.

### 7. CLI `zonepad mapping`

```bash
zonepad mapping draft --device <stable_id|eventN> [--connection usb|bluetooth|desconhecida]
                      [--out PATH] [--print] [--force] [--sysfs-root PATH]
zonepad mapping show    --device <stable_id|eventN> [--json]
zonepad mapping validate PATH
```

- `draft`: descobre, resolve a identidade, aplica catálogo/override, valida e grava; sem `--out` usa o layout de D7.
- `draft` exige confirmação explícita quando a identidade é ambígua (D5); `--force` só sobrescreve mapping existente, nunca contorna ambiguidade.
- `show`: imprime o mapping salvo e a proveniência (provisório ou confirmado, catálogo, data).
- `validate`: valida um arquivo arbitrário e reporta erros por campo; útil para mappings manuais e importados.
- Mensagens em PT-BR, sem stack trace, com próximo comando sugerido (`zonepad calibrate --device <id>`).
- Exit codes: `0` sucesso; `2` referência ambígua, argumentos inválidos ou mapping existente sem `--force`; `3` dispositivo ausente; `4` capabilities insuficientes para os canais obrigatórios; `1` falha inesperada.

### 8. Integração com `run` e `calibrate`

- `--device` aceita ID estável ou `eventN`. Se for `eventN`, resolva a identidade e use-a para achar mapping salvo.
- Ordem de resolução do mapping: `--mapping` explícito > mapping salvo da identidade/conexão > erro com exit `2` explicando como criar (`zonepad mapping draft --device <id>`).
- `--mapping` deixa de ser obrigatório no parser de `run` e `calibrate`, mas continua aceito e continua vencendo; remova as mensagens que hoje dizem "mapping é necessário" (`cli.py:279-284`) e cubra o novo caminho com testes.
- `calibrate` sem `--device` lista apenas gamepads descobertos, com ID estável e `eventN` visível, mantendo a escolha por número; confirmação mostra identidade, conexão e origem do mapping.
- Nenhuma mudança no wizard, nas métricas ou no perfil: a integração termina na resolução do mapping e do nó.
- `run` imprime em `INFO` (sem poluir stdout) o ID resolvido, o nó e a origem do mapping.

### 9. Hot-plug

- Porta `HotplugWatcher` com `snapshot()` e `poll() -> HotplugChange` contendo `added` e `removed` de identidades estáveis.
- Implementação padrão por polling do sysfs com intervalo injetado (padrão 1 s) e relógio injetado; sem `inotify`, sem `udev`, sem root, sem dependência nova.
- `devices --watch` (ou `zonepad devices --follow`) imprime adições/remoções até Ctrl+C, com exit `130`; `--once` deixa o comportamento atual.
- Integração com `calibrate`: por padrão a seleção usa um snapshot único; se a spec aprovar, a tela de escolha atualiza a lista via watcher enquanto aguarda a resposta, sem nunca reconectar durante a captura.
- Reconexão automática do runtime **fica fora**; se a spec quiser incluir, precisa justificar escopo, testabilidade e riscos, e o usuário precisa aprovar.
- Nenhum loop infinito nos testes: o watcher é exercitado com snapshots roteirizados e relógio fake.

### 10. Documentação

- `docs/specs/device-discovery-v1.md`: problema, usuário, identidade, filtro, capabilities, catálogo, mapping draft, proveniência, precedência, CLI, hot-plug, exit codes e decisões D1–D14.
- `docs/adr/0006-descoberta-e-identidade-de-dispositivos.md`: contrato público, identidade, persistência, precedência de mapping e compatibilidade com `eventN`. Confirme que 0006 é o próximo número livre.
- `README.md`: seção de descoberta, exemplos copiáveis, layout de `~/.config/zonepad/devices/`, limitações (draft provisório, duplicados, Bluetooth, permissões) e fluxo recomendado `devices` → `mapping draft` → `calibrate` → `run`.

## Fora de escopo

- GUI/PySide6 (prompt 05) e qualquer widget de descoberta.
- Windows, macOS e backends não evdev.
- Schema de perfil v2, novos campos em mapping v1, alteração de `schema_version`.
- Alterar fórmulas, thresholds, unidade ou semântica de métricas de `docs/specs/metrics-v1.md`.
- Redesenhar o wizard, o protocolo de captura ou a política de retry.
- Reconexão automática do runtime, emulação, remapeamento global, firmware ou kernel.
- Dependências novas (`pyudev`, `evdev`, `hidapi`) sem aprovação explícita.
- Push, PR, merge ou rebase.

## Critérios de aceite

- [ ] `zonepad devices` lista apenas gamepads e não inclui teclado, mouse ou touchpad na saída padrão.
- [ ] `zonepad devices --all` mostra os candidatos excluídos com o motivo da exclusão.
- [ ] A descoberta funciona com `--sysfs-root` apontando para fixtures, sem `/sys` real.
- [ ] O ID estável não contém `eventN` e permanece o mesmo entre duas execuções sobre o mesmo fixture.
- [ ] Dois controles idênticos sem `uniq`/`phys` recebem IDs distintos, determinísticos e com aviso de fragilidade.
- [ ] Nenhum `open()` em `/dev/input/event*` ocorre em `devices` ou `mapping draft`.
- [ ] `mapping draft` gera arquivo aceito por `load_device_mapping` sem edição manual.
- [ ] O mapping gerado é idêntico em duas execuções sobre o mesmo fixture (determinismo).
- [ ] Mapping existente não é sobrescrito sem `--force`; `--print` não grava arquivo.
- [ ] Capabilities insuficientes listam os canais ausentes e retornam `4`, sem gravar mapping parcial.
- [ ] `identity.json` registra `provisional=true` quando centro/repouso vieram de absinfo ou do catálogo.
- [ ] `mapping show` e `mapping validate` reportam erros por campo, sem stack trace.
- [ ] `run --device <stable_id> --profile <uuid>` resolve o mapping salvo e executa com o mesmo resultado de um `--mapping` explícito equivalente.
- [ ] `run --device eventN --mapping <path>` continua funcionando exatamente como antes.
- [ ] `--mapping` explícito vence o mapping salvo; divergência é registrada em `INFO`.
- [ ] `calibrate --device <stable_id>` funciona sem `--mapping` e confirma identidade, conexão e origem do mapping.
- [ ] Dispositivo desconhecido retorna `3`; identidade ambígua retorna `2` com lista de candidatos.
- [ ] `zonepad list` permanece inalterado e há teste de regressão para `list`, `run`, `measure`, `replay`, `profiles` e `calibrate`.
- [ ] Watcher detecta adição e remoção com snapshot roteirizado e relógio fake, sem `sleep` real.
- [ ] Nenhum teste acessa `/sys`, `/dev/input`, `/dev/uinput` ou depende de hardware, TTY real ou rede.
- [ ] `docs/specs/device-discovery-v1.md`, ADR 0006 e README atualizados com exemplos copiáveis.
- [ ] `python scripts/sync_ai_assets.py --check` limpo se `ai/` foi alterado.

## Testes obrigatórios

Use `pytest`, `tmp_path`, fixtures de sysfs (diretórios com `device/id/*`, `capabilities/*`, `uevent`) e relógio fake. Nenhum hardware.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Gamepad USB | fixture com `ABS_X/Y/RX/RY/Z/RZ` e `BTN_SOUTH` | descoberto, ID `<bus>-<vid>-<pid>-<uniq>`, mapping draft completo |
| Teclado | fixture com `KEY_A`, `EV_KEY` e sem `ABS` | excluído por padrão; motivo em `--all` |
| Mouse | fixture com `REL_X/Y` e `BTN_LEFT` | excluído por padrão |
| Touchpad | `INPUT_PROP_POINTER` + `ABS_MT_POSITION_X` | excluído por padrão |
| Device virtual | `name`/`uniq` de uinput ou Steam Input | classificado como `unknown` com aviso; `--all` mostra |
| Symlink quebrado | `device` inexistente | candidato `unknown` com motivo; descoberta continua |
| Sem permissão | fixture com erro simulado de leitura | motivo `permission_denied`; exit `3` só se nada sobrar |
| Duplicados | dois fixtures idênticos sem `uniq` | IDs `...-1`/`...-2` determinísticos + aviso |
| Bluetooth | `bustype=0x0005`, `uniq` = MAC | `connection=bluetooth`, ID estável com `uniq` |
| Range inesperado | `ABS_X` em `0..4095` | draft usa o range real, não defaults |
| Sem trigger | ausência de `ABS_Z`/`ABS_RZ` | exit `4`, lista canais ausentes, nenhum arquivo gravado |
| Draft determinístico | mesma fixture, duas execuções | arquivos byte-idênticos, mesmos hashes |
| Mapping existente | arquivo já salvo | recusa sem `--force`; `--force` sobrescreve atomicamente |
| Mapping inválido | JSON com campo desconhecido | `mapping validate` reporta o campo e retorna `2` |
| Precedência | mapping salvo + `--mapping` explícito | explícito vence; `INFO` registra divergência |
| Compat `eventN` | `run --device event3 --mapping m.json` | comportamento idêntico ao atual |
| Compat `list` | `zonepad list` | saída JSON por linha inalterada |
| Hot-plug | snapshot 1 sem device, snapshot 2 com device | `added` com ID correto; `removed` no inverso; sem sleep real |
| Dispositivo ausente | ID desconhecido | exit `3` com mensagem acionável |
| Regressão | suíte atual | testes existentes inalterados e verdes |

Adicione um teste que garanta que nenhum módulo de `domain/` importa `os`, `pathlib`, `evdev`, `time` ou `subprocess`, e outro que garanta que `devices`/`mapping draft` não abrem arquivos fora da raiz sysfs injetada.

## Validação

Execute e reporte a saída:

```bash
python --version
python -m pytest -q
ruff check .
ruff format --check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
zonepad devices --help
zonepad mapping --help
zonepad mapping draft --help
zonepad run --help
zonepad calibrate --help
```

Smoke com fixtures (sempre executável, sem hardware):

```bash
zonepad devices --sysfs-root tests/fixtures/sysfs --json
zonepad mapping draft --device <id> --sysfs-root tests/fixtures/sysfs --print
```

Smoke manual opcional, com dispositivo real e autorização explícita:

```bash
zonepad devices
zonepad devices --json
zonepad mapping draft --device <id> --print
zonepad calibrate --device <id>
zonepad run --device <id> --profile <uuid>
```

Se `ruff format --check` já falhar em `main` em arquivo fora do escopo, registre o débito e não o amplie. Se uma ferramenta não estiver disponível, declare exatamente o que não foi executado. Não execute `sudo`, não altere permissões e não acesse hardware sem confirmação.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Sysfs varia entre kernels e drivers | campos ausentes ou formato diferente | leitura tolerante por campo, motivo explícito por device, fixtures com variantes e aviso em vez de exceção |
| Filtro errado exclui gamepad legítimo | usuário não encontra o controle | critérios em D2 revisados por `controller-hardware`, `--all` sempre disponível, motivo por candidato |
| Device virtual (Steam Input, uinput, xpadneo) | duplicata ou identidade falsa | classificar como `unknown`, listar só com `--all`, documentar no README |
| Duplicados sem `uniq`/`phys` | mapping aplicado ao controle errado | sufixo determinístico + confirmação obrigatória + aviso de fragilidade |
| Bluetooth com MAC em `uniq` | ID muda ao reparar o dispositivo | hierarquia documentada; `identity.json` registra `uniq` e `connection` para diagnóstico |
| Centro/repouso provisórios do draft | métricas distorcidas se o usuário pular a calibração | `provisional=true`, aviso na CLI, README explícito e recomendação de `calibrate` |
| Permissões em `/dev/input` | `devices` funciona e `run` falha | descoberta sem abrir o nó; mensagem acionável de grupo `input`; sem `sudo` |
| Regressão em `run`/`calibrate` | quebra do fluxo atual | `--mapping` e `eventN` preservados; testes de regressão explícitos |
| Polling flaky ou caro | testes instáveis e CPU ociosa | intervalo injetado, relógio fake, snapshots roteirizados, sem `sleep` real |
| Catálogo desatualizado | ranges ou botões errados por família | absinfo vence o catálogo, divergência vira aviso, catálogo versionado e revisado por `controller-hardware` |
| Escopo crescente (hot-plug/reconexão) | incremento não fecha | D11 fixa polling e exclui reconexão do runtime; mudança exige aprovação do usuário |
| Dependência nova | packaging e CI impactados | proibida sem aprovação; alternativa sempre por stdlib |

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 3–6 bullets com a ordem real das etapas e onde houve handoff.
2. **Spec e decisões** — caminho de `device-discovery-v1.md`, ADR 0006 e decisões D1–D14 fechadas, com o que mudou em relação às recomendações.
3. **Mudanças por arquivo** — domínio, adapters, registry, catálogo, CLI, integração, watcher, testes e docs.
4. **Contratos** — assinaturas das portas, formato do ID estável, layout de `identity.json` e exit codes.
5. **Compatibilidade** — evidência de que `list`, `run`, `measure`, `replay`, `profiles` e `calibrate` continuam funcionando, com os comandos usados.
6. **Testes e validações** — comandos, resultados e o que não foi executado.
7. **Smoke com hardware** — dispositivo, VID/PID, ranges, mapping gerado e pendências; declare explicitamente se não foi feito.
8. **Riscos e limitações** — filtro, identidade, draft provisório, hot-plug e cobertura por família.
9. **Próximo passo** — handoff para o prompt 05 e o que fica como seam de GUI.

## Invocação

### Claude Code (prioritária)

```text
Use o prompt em @ai/prompts/04-device-discovery-mapping.md.
Leia o arquivo inteiro antes de agir e siga a tabela "Etapas e responsáveis" na ordem.
Trabalhe no checkout principal, sem git worktree, na branch feat/device-discovery-mapping
criada a partir da main; confirme os gates de "Pré-condições" antes de qualquer edição.
Comece com /flow-design-feature e NÃO escreva código de produção antes de a spec
docs/specs/device-discovery-v1.md e o ADR 0006 serem aprovados pelo usuário.
Delegue a controller-hardware: identidade estável, critérios de filtro de gamepads,
interpretação de capabilities evdev/sysfs, catálogo e overrides por família, política de
hot-plug e revisão dos números do smoke. Ele não implementa código de produção.
Delegue a python-engineer: adapters de descoberta, modelo de identidade, registry,
geração e persistência de mapping, watcher de hot-plug, CLI devices/mapping, integração
com run/calibrate, testes e documentação técnica.
Use prompt-engineer apenas se houver mudança em ai/ ou inconsistência entre prompt,
README e spec.
Implemente com /flow-implement-feature e faça a revisão final com /flow-review-calibration.
Valide com os comandos da seção "Validação" e entregue o relatório no "Formato de saída".
```

### Codex (alternativa)

```text
Siga o prompt em ai/prompts/04-device-discovery-mapping.md.
Leia o arquivo inteiro e execute as etapas na ordem, no checkout principal, sem worktree,
na branch feat/device-discovery-mapping criada a partir da main.
Use $flow-design-feature para a spec e o ADR, $flow-implement-feature para o código e
$flow-review-calibration para a revisão. Não escreva código antes da aprovação da spec.
Delegue identidade, filtro de gamepads, capabilities, catálogo, hot-plug e revisão dos
números a controller-hardware. Delegue descoberta, identidade, registry, mapping, watcher,
CLI, integração, testes e docs a python-engineer. Use prompt-engineer apenas para ai/.
Valide com pytest, ruff, mypy, sync --check e o --help dos subcomandos.
```

Se os fluxos não existirem no harness, siga `ai/flows/flow-design-feature/FLOW.md`, `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, e registre o fallback.

## Sequência

- **Prompts 00–03 (concluídos):** toolchain, runtime, motor de métricas e wizard.
- **Prompt 04 (este):** descoberta e mapeamento por família; substitui a seleção manual e o mapping escrito à mão.
- **Prompt 05:** GUI sobre o mesmo núcleo, consumindo `devices` e `mapping`.
- **Prompt 06:** qualidade, cobertura e release.

Não antecipe GUI, schema v2 ou reconexão automática. Se a implementação precisar de uma decisão do prompt 05, registre a pendência e mantenha a descoberta atrás de porta.

## Handoff para o prompt 05

Entregue ao próximo incremento:

1. As portas de descoberta, identidade, catálogo, registry e watcher, com os contratos e os fakes usados nos testes.
2. O layout de `~/.config/zonepad/devices/` e o formato de `identity.json`, para a GUI reutilizar sem duplicar lógica.
3. Os exit codes e mensagens de erro por comando, para a GUI traduzir em estados de tela.
4. As limitações conhecidas (filtro, duplicados, draft provisório, Bluetooth, hot-plug por polling) e o que foi validado em hardware real.
