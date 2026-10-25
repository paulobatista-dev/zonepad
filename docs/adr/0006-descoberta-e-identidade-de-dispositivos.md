# ADR 0006 — Descoberta e identidade estável de dispositivos

- **Status:** aceito (aprovado pelo usuário em 2026-10-25)
- **Data:** 2026-10-25
- **Spec:** [`docs/specs/device-discovery-v1.md`](../specs/device-discovery-v1.md)

## Contexto

Hoje `zonepad run` e `zonepad calibrate` exigem que a pessoa informe o nó `eventN` e um mapping JSON v1 escrito à mão (ADR 0003; ADR 0005, item 8). O `eventN` muda entre boots e reconexões. `LinuxEvdevBackend.list_devices` lista todo `event*` sem filtro e sem VID/PID (`src/zonepad/infrastructure/evdev.py:131-137`). O mapping v1 é estrito e rejeita campos desconhecidos (`src/zonepad/infrastructure/mapping.py:169-172`), por isso não pode carregar identidade nem proveniência.

O sysfs expõe, sem abrir o nó e sem privilégio, os seguintes dados:

- nome;
- `id/{bustype,vendor,product,version}`;
- `uniq` e `phys`;
- driver;
- bitmaps de capabilities e de propriedades.

O sysfs **não** expõe `input_absinfo`. `capabilities/abs` é só um bitmap (`drivers/input/input.c:1586-1607`), e os ranges saem apenas pelo ioctl `EVIOCGABS` com o nó aberto (`drivers/input/evdev.c:1207-1219`). `DeviceInfo.device_id` alimenta frames, capturas, manifestos e diretórios de sessão. O nome `DeviceIdentity` já designa o bloco `device` do perfil v1 (`src/zonepad/domain/profile.py:221`).

## Decisão

1. **Descoberta.** É feita por uma porta `InputDeviceScanner`, que lê `<sysfs_root>/class/input/event*`.
   - `<sysfs_root>` é o ponto de montagem (padrão `/sys`), e todo caminho resolvido precisa estar sob ele.
   - `zonepad devices` só abre nós de `/dev/input` com `--verify`.
2. **Ranges.** São lidos por uma porta separada, `AbsInfoReader`.
   - `mapping draft` abre só o nó resolvido, com `O_RDONLY | O_NONBLOCK | O_CLOEXEC`, executa `EVIOCGABS` via `fcntl.ioctl` e fecha. Não lê eventos.
   - Sem permissão, usa os ranges do catálogo; se não houver, sai com exit 3 e uma mensagem acionável.
   - `--no-probe` desliga a leitura do nó.
   - Isso implementa a "fonte complementar" prevista na ADR 0003 sem retirar a autoridade do mapping JSON. (P1, aprovada.)
3. **Classificação.** É feita por regras ordenadas sobre as capabilities, e cada candidato recebe classe e motivo estável.
   - As classes são `gamepad`, `keyboard`, `mouse`, `touchpad`, `motion_sensor`, `virtual` e `unknown`.
   - O dispositivo virtual é detectado pelo caminho `/devices/virtual/input/` ou por `BUS_VIRTUAL`. Assim o controle virtual do próprio ZonaPad, que anuncia `BUS_USB`, nunca é tratado como gamepad.
4. **Identidade.** É um tipo novo de domínio, `StableIdentity` com `HardwareFacts`.
   - `DeviceInfo` continua sendo o tipo de sessão, com `device_id = eventN`.
   - Capturas, manifestos, perfis e `zonepad list` não mudam.
5. **Formato do ID.** O ID estável segue `<bus>-<vid>-<pid>-<qualificador>[.<n>]`, em ASCII minúsculo, e é validado por regex antes de virar caminho.
   - O qualificador segue a ordem `uniq` > serial USB > `phys` (só em USB) > ocorrência.
   - Ele é codificado como `u`, `s` ou `p` seguido de 10 hex de SHA-256, ou como `n<k>` na ocorrência.
   - Qualificadores idênticos recebem `.2`, `.3`.
   - `eventN` e `name` nunca entram no ID.
   - IDs por ocorrência ou duplicados são `fragile` e exigem confirmação explícita para gravar mapping. (P3, aprovada: hash sem sal, pseudônimo.)
6. **Chave de persistência.** É `(stable_id, connection)`. O store busca pelo `stable_id` e só compara a conexão quando a conexão detectada for conhecida.
   - `device_version` (`bcdDevice`) e `firmware` (exposto só por hid-playstation) ficam no sidecar.
   - Uma mudança nesses valores gera aviso, sem bloquear.
   - Não há fallback entre chaves.
7. **Armazenamento.** Os mappings ficam em `~/.config/zonepad/devices/<stable_id>/mapping.json`, com o schema v1 sem mudanças.
   - Ao lado ficam `identity.json` (schema próprio, `schema_version: 1`) e um `index.json` de cache.
   - A gravação é atômica, na ordem mapping → identity → índice.
   - Quando o índice está ausente ou inconsistente, ele é reconstruído a partir dos sidecars.
   - O valor cru de `uniq`, serial e `phys` existe só no sidecar local.
8. **Draft.** Todo draft é provisório (`provisional=true`).
   - O range vem de absinfo; sem absinfo, de `known_ranges` do catálogo.
   - O centro de stick é `(min+max+1)//2`, a menos que o catálogo traga um override.
   - O repouso de trigger é igual ao mínimo.
   - Um draft parcial nunca é gravado.
9. **Catálogo.** É JSON versionado, empacotado como package data e lido de forma estrita, com match por driver e VID:PID.
   - O absinfo vence os ranges do catálogo.
   - Uma família desconhecida passa por uma heurística genérica, que exige confirmação quando há ambiguidade de eixos.
10. **Precedência do mapping.** `--mapping` explícito vence o mapping salvo da chave atual. Sem nenhum dos dois, sai com exit 2 indicando `zonepad mapping draft --device <id>`.
    - Um `--mapping` inválido nunca cai para o salvo.
    - A divergência entre explícito e salvo é registrada em `INFO`.
11. **`--device`.** Aceita ID estável, `eventN` ou a base `<bus>-<vid>-<pid>` quando ela é única.
    - `eventN` com `--mapping` explícito segue o caminho legado, sem consultar sysfs nem store.
    - Nos outros casos, a resolução acontece antes do `open`, o backend continua recebendo `eventN` e os fatos de identidade são conferidos depois do `open`.
    - Dispositivo ausente retorna 3 em todos os comandos, inclusive `run`, que hoje retorna 2. (P5, aprovada.)
12. **`calibrate`.** Muda só a ordem no composition root: seleção do dispositivo, depois resolução do mapping, depois construção do backend.
    - Usa os efeitos `select_device` → `validate_mapping` → `confirm_device` que já existem.
    - Reducer, wizard, métricas e perfil não mudam.
13. **Hot-plug.** Usa `PollingHotplugWatcher` na camada de aplicação, com `InputDeviceScanner` e a porta `Clock` existente, em intervalo padrão de 1 s.
    - A comparação é pelo token `inputM`, que não se repete dentro do boot. Ela emite `added`, `removed` e `renamed` (renumeração de gêmeos).
    - Reconexão automática do runtime fica fora.
14. **Testes.**
    - A raiz sysfs é gerada em `tmp_path`.
    - Leitor de absinfo, store, catálogo e relógio são fakes.
    - Um audit hook restringe `open` e `scandir` à raiz e proíbe `ioctl`.
    - Um teste de arquitetura impede `os`, `pathlib`, `time`, `evdev`, `subprocess`, `fcntl`, `select` e `struct` em `domain/`.

## Consequências

- O fluxo `devices` → `mapping draft` → `calibrate` → `run` dispensa `eventN` e mapping manual, sem alterar os schemas de mapping, perfil, captura e manifesto.
- `mapping draft` só exige permissão de leitura do nó para família não catalogada. Família catalogada cai automaticamente para os ranges do catálogo quando falta permissão.
- O `stable_id` é pseudônimo, não anônimo: o hash de um MAC é reversível por força bruta.
- `run` e `calibrate` conferem o absinfo, com um `open` separado, só quando o range salvo veio do catálogo. A divergência vira aviso `absinfo_mismatch`.
- O mapping gerado é provisório. Nenhum comando deste incremento grava `provisional=false`.
- Switch Pro é reconhecido, mas não gera mapping v1 (triggers digitais), e sai com exit 4.
- IDs por ocorrência podem trocar entre gêmeos idênticos. A CLI avisa e exige confirmação.
- O teste que exige a mensagem "`--mapping` é necessário" em `run` passa a exigir a orientação de `mapping draft`.
- O exemplo `usb-045e-02ea-<serial>` do prompt 04 vira `usb-045e-02ea-s<hash>`. O xpad não preenche `uniq`.

## Alternativas consideradas

- **Ler ranges só do catálogo (sem `open`).** Viável, mas impede o draft de HID genérico e torna "absinfo vence catálogo" inverificável. Fica disponível via `--no-probe`.
- **Ler o HID report descriptor.** Rejeitada: o xpad não é HID, os drivers sobrescrevem os ranges e seria preciso um parser HID completo.
- **Estender `DeviceInfo` com `uniq`/`phys`.** Rejeitada: afeta cerca de 20 construtores, o manifesto e a derivação do perfil, e mistura identidade de sessão com identidade persistida.
- **Adicionar `device`/`firmware` ao mapping v1.** Rejeitada: o parser rejeita campos desconhecidos, e o schema v1 é contrato público.
- **Usar `eventN`, `name` ou o caminho sysfs como chave.** Rejeitada: os três são voláteis.
- **Incluir firmware ou `id/version` na chave.** Rejeitada: `id/version` é `bcdDevice`; incluí-lo quebraria a busca a cada atualização, sem ganho.
- **Sufixo `-2` para duplicados.** Rejeitada: é ambíguo para o leitor. O `.` nunca aparece num qualificador.
- **`--sysfs-root` em `/sys/class/input`.** Rejeitada: os symlinks resolvem para `/sys/devices`, o que impede o confinamento.
- **Hot-plug por udev, netlink ou inotify.** Rejeitada neste incremento: exige dependência nova ou complexidade sem ganho sobre polling de 1 s.
- **`monkeypatch` de `open` no teste de confinamento.** Rejeitada: `Path.read_text` e `io.open` escapam. O audit hook cobre todos os caminhos.
