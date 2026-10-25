# Spec — Descoberta de dispositivos e mapping por família (v1)

- **Status:** aprovada pelo usuário em 2026-10-25, com as recomendações de P1–P9.
- **Data:** 2026-10-25.
- **Prompt:** [`ai/prompts/04-device-discovery-mapping.md`](../../ai/prompts/04-device-discovery-mapping.md).
- **ADR:** [`docs/adr/0006-descoberta-e-identidade-de-dispositivos.md`](../adr/0006-descoberta-e-identidade-de-dispositivos.md).
- **Pareceres:** `controller-hardware` (identidade, filtro, capabilities, catálogo, centro provisório, permissões, hot-plug) e `python-engineer` (contratos, persistência, CLI, testes), consolidados pelo agente principal.
- **Evidência de kernel:** `torvalds/linux` no commit `330517c63aa9`, lido pelo `controller-hardware` sem acesso a `/sys`, `/dev/input` ou hardware desta máquina. Os números de linha `arquivo.c:N` referem-se a esse commit.
- **Convenção:** **FATO** = lido em fonte primária; **INFERÊNCIA** = derivado e sujeito a erro; **LACUNA** = não verificado, a confirmar no smoke com hardware.

## Problema

Hoje `zonepad run` e `zonepad calibrate` dependem de dois dados que a pessoa obtém à mão:

1. **O nó `eventN`**, que muda entre boots e reconexões. `LinuxEvdevBackend.list_devices` lista todo `event*` sem filtro e sem VID/PID (`src/zonepad/infrastructure/evdev.py:131-137`).
2. **Um mapping JSON v1 escrito à mão**, com códigos e ranges (ADR 0003; `cli.py:279-284`; `calibration_cli.py:194-195`).

## Usuário e contexto

- **Quem:** pessoa em Linux que quer calibrar e usar um gamepad sem conhecer códigos evdev nem descobrir qual nó é o controle.
- **Ambiente:** sessão gráfica local. Ler o sysfs não exige privilégio; abrir o nó `/dev/input/eventN` exige ACL `uaccess` ou o grupo `input`.
- **Alvos:** Xbox (xpad), DualShock 4 e DualSense (hid-playstation), Switch Pro (hid-nintendo), 8BitDo em modo X-input e HID genérico.

## Resultado esperado

```bash
zonepad devices
zonepad mapping draft --device usb-045e-02ea-s1a2b3c4d5e
zonepad calibrate --device usb-045e-02ea-s1a2b3c4d5e
zonepad run --device usb-045e-02ea-s1a2b3c4d5e --profile <uuid>
```

O fluxo funciona assim:

- O sistema lista só gamepads e identifica cada um por um ID estável que não depende de `eventN`.
- Gera um mapping `schema_version=1` válido a partir de capabilities, ranges reais do dispositivo e um catálogo por família.
- Persiste esse mapping por identidade e o resolve sozinho em `run` e `calibrate`.

O mapping gerado é **provisório**. Os ranges vêm do driver; centro e repouso são declarados, não medidos, até o wizard medir.

Continuam funcionando:

- `eventN` como referência de dispositivo;
- `--mapping` explícito, que vence qualquer mapping salvo;
- `zonepad list`, sem nenhuma mudança.

## Escopo

1. Descoberta Linux por `<sysfs_root>/class/input/event*`, sem abrir o nó.
2. Classificação por capabilities: `gamepad`, `keyboard`, `mouse`, `touchpad`, `motion_sensor`, `virtual` e `unknown`, sempre com motivo.
3. Identidade estável com qualificador hierárquico e tratamento de duplicados.
4. Modelo de capabilities a partir dos bitmaps do sysfs e do absinfo lido pela porta `AbsInfoReader`.
5. Catálogo declarativo e versionado por família, com camada de override do usuário e heurística genérica.
6. Geração, validação e persistência de mapping v1, com sidecar `identity.json` e `index.json`.
7. CLI `zonepad devices` e `zonepad mapping {draft,show,validate}`.
8. `run` e `calibrate` aceitando ID estável e resolvendo o mapping salvo.
9. Watcher de hot-plug por polling, com relógio injetado.
10. Spec, ADR 0006, README e testes determinísticos sem hardware.

## Fora de escopo

- GUI (prompt 05), Windows, macOS e backends não evdev.
- Schema de perfil v2, novos campos no mapping v1 e mudança de `schema_version`.
- Fórmulas, thresholds e semântica de métricas (`docs/specs/metrics-v1.md`).
- Redesenho do wizard, do protocolo de captura ou da política de retry.
- Reconexão automática do runtime.
- VID/PID reais em `DeviceInfo`, manifesto e perfil (ver P8).
- Leitura do HID report descriptor: o xpad não é HID, os drivers sobrescrevem ranges e seria preciso um parser HID completo.
- Dependências novas (`pyudev`, `evdev`, `hidapi`), udev, netlink e inotify.
- `sudo`, mudança de permissões, regras udev, push, PR e merge.

## Mudanças em relação ao prompt 04

Cada item tem evidência na seção indicada. Os itens marcados com **P** dependem da sua aprovação.

| # | Prompt diz | Esta spec define | Motivo |
| --- | --- | --- | --- |
| M1 | Ranges vêm de `capabilities/abs` no formato `code:min:max:flat:fuzz:res` (Escopo §3, D1, D9) | `capabilities/abs` é só um bitmap de presença. Os ranges vêm do ioctl `EVIOCGABS` (porta `AbsInfoReader`) ou do catálogo | FATO: `drivers/input/input.c:1586-1607` e `:1557-1584`; absinfo só em `drivers/input/evdev.c:1207-1219`; `Documentation/input/event-codes.rst:18-25` |
| M2 | Nenhum `open()` em `/dev/input` durante `mapping draft` | `devices` nunca abre o nó (exceto com `--verify`). `mapping draft` abre só o nó resolvido, `O_RDONLY`, apenas para `EVIOCGABS`, sem ler eventos. `--no-probe` usa só o catálogo | Sem `open()`, HID genérico não tem range nenhum. **P1** |
| M3 | `sysfs_root = /sys/class/input` | `sysfs_root = /sys` (ponto de montagem); enumeração em `<root>/class/input/event*` | `class/input/eventN` resolve para `<root>/devices/...`, e o serial USB e o driver também ficam ali. **P2** |
| M4 | Hierarquia `uniq > phys > serial > índice` | `uniq > usb_serial > phys` (só USB) `> ocorrência` | xpad nunca define `uniq` (`xpad.c:1955-1957`); em Bluetooth, `phys` é o MAC do adaptador (`net/bluetooth/hidp/core.c:800-807`) |
| M5 | ID com `uniq`/serial legível (`usb-045e-02ea-<serial>`) | Qualificador em hash: `u`/`s`/`p` + 10 hex de SHA-256 | Serial e MAC são identificadores pessoais e iriam parar em caminhos, logs e relatórios. **P3** |
| M6 | Duplicados com `-1`/`-2` (teste) ou `-2`/`-3` (D4) | Ocorrência sem qualificador: `n1`, `n2`. Qualificador repetido: o primeiro sem sufixo, os demais `.2`, `.3` | O prompt se contradiz. O `.` nunca aparece num qualificador, então não há colisão |
| M7 | Duplicado = mesmo `vid`/`pid`/`uniq` com `phys` ausente | Duplicado = mesma tupla completa `(bustype, vid, pid, fonte, qualificador)` | Os 4 pads do receptor 360W compartilham `phys` (`xpad.c:2076-2077`) |
| M8 | Device virtual → `unknown` | Classe própria `virtual`, detectada pelo caminho `/devices/virtual/input/` ou por `BUS_VIRTUAL` | O controle virtual do próprio ZonaPad anuncia `BUS_USB` 1234:0001 (`uinput.py:40`, `:67`) e passa no filtro de gamepad |
| M9 | Excluir dispositivos com `KEY_A`/`KEY_SPACE` | Teclado = bloco completo de teclas 1..31, ou `KEY_A`+`KEY_SPACE` **sem** `ABS_X/Y` | Pads legítimos anunciam `KEY_*`, como o `KEY_RECORD` do xpad (`xpad.c:1988-1989`) |
| M10 | Faixa `ABS_MT_*` = `0x2f..0x3e` | `0x2f..0x3d` | `ABS_MT_TOOL_Y = 0x3d`; `0x3e` não está definido |
| M11 | `firmware` na chave de persistência (D6) | Chave = `(stable_id, connection)`. `device_version` e `firmware` ficam no sidecar; mudança gera aviso | `id/version` é o `bcdDevice` USB, não firmware (`include/linux/usb/input.h:19`); firmware real só existe em hid-playstation (`hid-playstation.c:993-1021`) |
| M12 | "Sem trigger" = falta `ABS_Z`/`ABS_RZ` | "Sem trigger" = nenhum par de trigger candidato na heurística (§ Catálogo) | Triggers podem vir em `ABS_GAS`/`ABS_BRAKE` ou `ABS_HAT2X/Y` (`Documentation/input/gamepad.rst:163-165`) |
| M13 | Ordem do absinfo `min:max:flat:fuzz:res` | A struct é `value, minimum, maximum, fuzz, flat, resolution` | `include/uapi/linux/input.h:93-100` |
| M14 | Bitmaps em "palavras de 64 bits" | A largura da palavra depende da ABI do processo leitor e é injetável (`bitmap_word_bits`) | `drivers/input/input-compat.c:100-120`: processo 32-bit lê palavras de 32 bits |
| M15 | `run` com dispositivo ausente: "exatamente como antes" (hoje exit 2) | Dispositivo ausente = exit 3 em todos os comandos | Igual ao que `calibrate` já faz (`calibration_cli.py:264-265`). **P5** |
| M16 | `devices --watch` ou `--follow`, `--once` | `--watch` e `--interval`. Não há `--once`, porque executar uma vez já é o padrão | Menos superfície |

## Requisitos funcionais

### RF1 — Leitura do sysfs (D1)

Todos os caminhos são relativos a `<root>/class/input/eventN/`. A leitura passa só por `SysfsInputScanner(root, bitmap_word_bits, read_text)`, o único módulo que toca `/sys`.

| Caminho | Formato (FATO, `input.c`) | Uso |
| --- | --- | --- |
| `device` → `../inputM` | symlink | `Path.resolve()`; o basename `inputM` é o token de registro |
| `device/name`, `device/phys`, `device/uniq` | `"%s\n"`, pode ser vazio | nome para exibição; qualificador |
| `device/id/{bustype,vendor,product,version}` | `"%04x\n"` | conexão, VID, PID e `device_version` |
| `device/properties` | bitmap, `INPUT_PROP_MAX=0x1f` | filtro |
| `device/capabilities/{ev,key,abs,rel,msc,sw,led,snd,ff}` | bitmap | filtro, canais e botões |
| `device/device/driver` → `.../drivers/<nome>` | symlink | chave de família do catálogo |
| `device/device/firmware_version` | `"0x%08x\n"`, só em hid-playstation | `firmware` |
| `device/device/bInterfaceProtocol` | `"%02x\n"`, interface USB | tipo xpad quando o PID não está na tabela |
| ancestral USB: `idVendor`, `idProduct`, `serial` | `"%s\n"`; `serial` só existe com iSerialNumber | `usb_serial` |
| `uevent`, `dev`, `device/uevent`, `device/modalias` | texto | diagnóstico |

**Decodificação de bitmap (FATO: `input_print_bitmap`, `input.c:1557-1584`).** O texto traz palavras em hex minúsculo, sem `0x` e sem zeros à esquerda. A primeira palavra é a mais significativa; as palavras são separadas por um espaço e o texto termina em `\n`.

1. `strip()` e `split(" ")`. Cada palavra precisa casar com `^[0-9a-fA-F]+$`.
2. A palavra de índice `i`, contado a partir da direita, contribui `int(w, 16) << (i * W)`.
3. `W = bitmap_word_bits` não se deduz do texto. O padrão é `8 * ctypes.sizeof(ctypes.c_ulong)`, e as fixtures declaram o valor.
4. Uma palavra com valor `>= 2**W`, um número de palavras acima do necessário ou um bit acima de `*_MAX` gera o motivo `malformed_bitmap:<attr>`.

**Leitura tolerante.**

- Remover só o `\n` final.
- Decodificar UTF-8 com `errors="replace"`, registrando aviso.
- Atributo opcional ausente vira `None`.
- `PermissionError` vira o motivo `permission_denied`.
- `device` que não resolve vira `broken_device_link`.
- `FileNotFoundError` no meio da leitura de um nó vira `vanished`: o nó é omitido do snapshot.
- Caminho resolvido fora de `root` vira `outside_sysfs_root`.
- Erro em um nó nunca aborta a varredura.

### RF2 — Classificação (D2)

As regras são avaliadas em ordem e a primeira que casar vence. Os códigos são os de `include/uapi/linux/input-event-codes.h`.

| # | Classe | Critério | Motivo |
| --- | --- | --- | --- |
| 0 | `unknown` | erro de leitura (RF1) | `broken_device_link`, `permission_denied`, `unreadable_attribute:<a>`, `malformed_bitmap:<a>` |
| 1 | `virtual` | o caminho resolvido de `inputM` contém o segmento `/devices/virtual/input/`, **ou** `bustype == 0x06`. O segmento `/devices/virtual/misc/uhid/` (Bluetooth real via BlueZ) **não** conta | `virtual:zonapad` (nome `ZonaPad Virtual Controller` e `1234:0001`); `virtual:steam_input` (VID `28de` ou nome contendo `Steam`, INFERÊNCIA); `virtual:uinput`; `virtual:bus_virtual` |
| 2 | `motion_sensor` | `INPUT_PROP_ACCELEROMETER` (0x06), **ou** sem `EV_KEY` e com `ABS_X`, `ABS_Y` e `ABS_Z` | `not_a_gamepad:motion_sensor` |
| 3 | `touchpad` | `ABS_MT_POSITION_X/Y` (0x35/0x36), **ou** `INPUT_PROP_POINTER` (0x00), **ou** `BTN_TOOL_FINGER` (0x145) sem `INPUT_PROP_DIRECT`. Com `INPUT_PROP_DIRECT` ou `BTN_TOOL_PEN`, a classe é `unknown` | `not_a_gamepad:touchpad`, `not_a_gamepad:touchscreen_or_tablet` |
| 4 | `gamepad` (`gamepad_kind=gamepad`) | `EV_ABS`, `ABS_X`, `ABS_Y`, `EV_KEY` e `BTN_SOUTH` (0x130). Se também houver `REL_X/Y` ou o bloco completo de teclado, a classe é `unknown` | `ambiguous:gamepad_and_mouse`, `ambiguous:gamepad_and_keyboard` |
| 5 | `gamepad` (`gamepad_kind=joystick_hid`) | `EV_ABS`, `ABS_X`, `ABS_Y` e algum código em `0x120..0x12f`, sem nenhum em `0x110..0x11f`. As exclusões da regra 4 valem aqui | aviso `face_buttons_not_positional` |
| 6 | `keyboard` | `EV_KEY` com os bits 1..31 todos ligados, **ou** `KEY_A` (30) e `KEY_SPACE` (57) sem `ABS_X/Y` | `not_a_gamepad:keyboard` |
| 7 | `mouse` | `REL_X` e `REL_Y`, **ou** botões `0x110..0x117` sem `ABS_X/Y` | `not_a_gamepad:mouse` |
| 8 | `unknown` | qualquer outro caso | `not_a_gamepad:no_abs_xy`, `not_a_gamepad:no_gamepad_buttons`, `not_a_gamepad:other` |

- A saída padrão mostra só `gamepad`. `--all` mostra todas as classes com o motivo.
- O controle virtual do ZonaPad aparece em `--all`, mas nunca é selecionável.
- Os motivos são strings ASCII estáveis, no formato `<categoria>[:<detalhe>]`.
- Casos reais cobertos (FATO):
  - DualSense e DS4 criam nós extras `Touchpad`, `Motion Sensors` e `Headset Jack` com o mesmo `uniq` (`hid-playstation.c:639-665`, `:910-980`);
  - Switch Pro cria um nó `(IMU)` (`hid-nintendo.c:2123-2183`);
  - xpadneo cria nós `Keyboard` e `Mouse` com o mesmo `uniq` e `phys`;
  - hid-playstation deixa `phys` vazio em dispositivo real, por isso `phys` vazio não indica dispositivo virtual.

### RF3 — Identidade estável (D3, D4, D5)

**Hierarquia do qualificador.** Só nós da classe `gamepad` recebem ID.

1. `uniq` não vazio depois da normalização → fonte `uniq`.
2. `bustype == 0x03`, `uniq` vazio e o ancestral USB tem `serial` não vazio → fonte `usb_serial`.
   - O ancestral USB é o primeiro diretório acima de `inputM` que tem `idVendor` e `idProduct`. A busca para em `<root>/devices`.
   - Ele só vale se `idVendor` for igual a `id/vendor`. Se `idProduct` divergir, como no receptor 360W (`0719` contra `02a1`), o resultado registra o aviso `usb_product_mismatch`.
3. `bustype == 0x03` e `phys` não vazio → fonte `phys`, com aviso `identity_bound_to_port`. Em Bluetooth, `phys` nunca é usado.
4. Nenhum dos anteriores → fonte `occurrence`, com aviso `identity_weak`.

**Normalização.**

- Remover espaços nas pontas.
- Um MAC que casa `^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$` vira 12 hex minúsculos sem separador. Assim `%pMR` (hid-playstation, minúsculo) e `%pMU` (hid-nintendo, maiúsculo) dão o mesmo valor.
- Outros valores ficam como estão, em NFC.
- Um valor só de zeros conta como vazio, com aviso `placeholder_serial`.
- `phys` é usado completo, com o sufixo `/inputN`. Em usbhid, o número da interface distingue nós físicos (`usbhid/hid-core.c:1431-1437`). No xpad o sufixo é sempre `/input0` (`xpad.c:2076-2077`).

**Formato do ID (D4).**

```text
stable_id := bus "-" vid "-" pid "-" qualifier [ "." dup ]
bus       := "usb" | "bt" | "bus" HEX4         ; 0x03 → usb, 0x05 → bt, demais → bus%04x
vid, pid  := HEX4                              ; hex minúsculo
qualifier := "u" HEX10 | "s" HEX10 | "p" HEX10 ; uniq | usb_serial | phys
           | "n" OCC                           ; ocorrência, 1-based
dup       := 2..99
```

```python
STABLE_ID_PATTERN = re.compile(
    r"(?:usb|bt|bus[0-9a-f]{4})-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"(?:[usp][0-9a-f]{10}(?:\.(?:[2-9]|[1-9][0-9]))?|n[1-9][0-9]{0,2})",
    re.ASCII,
)  # fullmatch; comprimento máximo 33; ".k" só existe após qualificador em hash
```

- `HEX10` = os 10 primeiros hex de `sha256(f"{fonte}\0{valor_canônico}".encode())`, com `fonte` em `uniq`, `usb_serial` ou `phys`.
- **Isso é pseudonimização, não anonimização.** Um MAC tem 48 bits; com o OUI do fabricante conhecido sobram cerca de 2^24 candidatos, e o hash pode ser revertido por força bruta. O `stable_id` não deve ser tratado como dado anônimo (ver P3).
- `n<k>`: `k` é a ordem pelo número de `eventN` (comparação numérica, não lexical) entre os gamepads com a mesma base `bus-vid-pid` e fonte `occurrence`. O sufixo existe mesmo com um único controle, para que um segundo controle idêntico não renomeie o primeiro.
- `.2`, `.3`: mesma base e mesmo qualificador em hash, como no 360W com `phys` comum ou em clones com o mesmo serial. O primeiro nó, pela ordem de `eventN`, fica sem sufixo.
- Todos os membros de um grupo `n<k>` ou `.k` ficam com `fragile=true` e recebem o aviso `duplicate_identity:<n>`.
- `eventN`, `name` e `sysfs_path` nunca entram no ID.
  - O `name` fica de fora porque no xpad ele vem da tabela do driver (`xpad.c:1955`) e pode mudar com o kernel.
- O ID é validado por `parse_stable_id` antes de virar `Path`: não contém `/`, `..` nem espaço.
- **Fragilidade, declarada:** o IDA do kernel reaproveita números de `eventN` (`input.c:2761-2768`). Trocar a ordem de conexão de dois aparelhos idênticos troca qual aparelho físico recebe `n1`.

**Conexão.** `0x03` → `usb`; `0x05` → `bluetooth`; qualquer outro valor → `unknown`, exibido como "desconhecida". Um dongle de 2,4 GHz aparece como `usb`: a conexão descreve o link entre host e dongle.

### RF4 — Capabilities e absinfo

- `DeviceCapabilities` traz:
  - tipos de evento;
  - eixos (`AxisCapability(code, absinfo: AbsInfo | None)`);
  - botões (`ButtonCapability(code)`);
  - eixos relativos;
  - propriedades;
  - canal sugerido.
- Validação:
  - `ABS_*` em `0x00..0x3f` e `KEY_*`/`BTN_*` em `0x000..0x2ff`;
  - sem duplicatas;
  - `AbsInfo.minimum < maximum`;
  - `fuzz`, `flat` ou `resolution` negativos não derrubam o dispositivo: são `__s32` sem restrição documentada (`input.h:93-100`). O valor é descartado (`None`) com o aviso `absinfo_negative_field:<campo>`.
- **`AbsInfoReader`** (variante recomendada, **P1**):
  - `os.open(node, O_RDONLY | O_NONBLOCK | O_CLOEXEC)`;
  - um `fcntl.ioctl(fd, EVIOCGABS(code), buffer de 24 bytes)` por código mapeado, com `struct.unpack("=6i")` na ordem `value, minimum, maximum, fuzz, flat, resolution`;
  - `os.close` em `finally`;
  - nunca chama `read()`.
  - Efeito colateral esperado (INFERÊNCIA, não verificada em hardware): o `open()` aciona o `open` do driver (o xpad submete URB; o HID chama `hid_hw_open`) durante um intervalo breve. Nenhum evento é consumido.
- O número do ioctl é calculado pela fórmula `_IOR('E', 0x40 + code, 24)`, que dá `0x80184540 + code` em x86_64 e aarch64.
- `value` é só diagnóstico (`value_at_probe`). Nunca vira centro nem repouso, porque é uma amostra única.
- `fuzz` e `flat` ficam registrados em `identity.json`. O kernel aplica o `fuzz` aos eventos ABS (`input.c:71-85`), então o ruído medido sobre evdev subestima o ruído do sensor. A métrica não muda neste incremento.

### RF5 — Catálogo por família (D10)

- Fica em `src/zonepad/infrastructure/catalog_data/families.json` (package data), com `catalog_version: 1`.
- O carregamento é estrito: campo desconhecido é rejeitado e nunca há `eval` ou `exec`.
- Campos de cada entrada:
  - `id`, `display_name`;
  - `match`, com `driver`, `bustype[]`, `vid_pid[] | null` e `usb_interface_protocol: {"in": [...]} | {"not_in": [...]} | null` (o `xpad-xbox360` casa com `not_in: ["81", "d0"]`, o `xpad-xbox360w` com `in: ["81"]` e o `xpad-xboxone` com `in: ["d0"]`);
  - `required_abs`;
  - `channels`;
  - `known_ranges`, com `minimum`, `maximum`, `fuzz` e `flat` por código;
  - `center_override`;
  - `buttons`, com chaves decimais;
  - `layout`, `unsupported_reason`, `quirks`, `evidence[]` e `verified_on_hardware`.
- **Busca:**
  - `driver` + `vid_pid` exato vence; depois vale a entrada de driver (`vid_pid: null`); por último, a heurística genérica.
  - O driver precisa bater.
  - Se faltar algum código de `required_abs` no bitmap, a entrada é descartada com o aviso `catalog_capability_mismatch`.
- **Precedência:**
  - override do usuário (`--catalog PATH`, mesmo schema, **P7**) > catálogo embutido > heurística genérica;
  - absinfo vence `known_ranges`, com aviso `catalog_range_mismatch:<code>`.

Entradas iniciais (FATO no kernel `330517c63aa9`; todas com `verified_on_hardware: false`):

| Entrada | Driver e VID:PID | Canais | Ranges | Botões faciais | Observação |
| --- | --- | --- | --- | --- | --- |
| `xpad-xbox360` | `xpad`: `045e:028e`, `028f`; `2dc8:3106`, `3109`, `310a`, `310b`, `6001`. Também casa como entrada de driver quando o protocolo da interface não é `81`/`d0` | lx/ly=X/Y, rx/ry=RX/RY, lt/rt=Z/RZ (`xpad.c:452-467`) | sticks `-32768..32767` (fuzz 16, flat 128); triggers `0..255` (`:1910-1921`) | 304/305/307/308 = S/E/N/W | `uniq` vazio; Y invertido pelo driver |
| `xpad-xbox360w` | `xpad`: `045e:02a1` (no input); USB `0719` | iguais a xpad-xbox360 | iguais a xpad-xbox360 | iguais a xpad-xbox360 | 4 pads com o mesmo `phys` → sempre `.k` |
| `xpad-xboxone` | `xpad`: `045e:02d1`, `02dd`, `02e3`, `02ea`, `0b00`, `0b0a`, `0b12`; `2dc8:2000`, `200f`, `201e`. Também casa como entrada de driver com protocolo `d0` | iguais a xpad-xbox360 | sticks iguais aos do 360; triggers `0..1023` | iguais a xpad-xbox360 | `KEY_RECORD` |
| `playstation-ds4` | `playstation`: `054c:05c4`, `09cc`, `0ba0` | X/Y, RX/RY, Z/RZ | todos os eixos `0..255` | Cruz/Círculo/Triângulo/Quadrado = S/E/N/W | `uniq` = MAC; `phys` vazio; tem `firmware_version` |
| `playstation-dualsense` | `playstation`: `054c:0ce6`, `0df2` | iguais a playstation-ds4 | iguais a playstation-ds4 | iguais a playstation-ds4 | tem nó `Headset Jack` |
| `nintendo-procon` | `nintendo`: `057e:2009` | sticks X/Y, RX/RY; ZL/ZR são **digitais** (`BTN_TL2/TR2`) | `-32767..32767` | B=S, A=E, X=N, Y=W | `unsupported_reason = digital_triggers_only` → exit 4 (**P4**) |

**Heurística genérica.** Exige classe `gamepad` e absinfo disponível. Sem absinfo: com `--no-probe`, exit 4 `ranges_unavailable`; com `DeviceAccessDeniedError`, exit 3 e a mensagem de permissão (RF13).

1. `lx` = `ABS_X` e `ly` = `ABS_Y`.
2. **Caso A** (com `ABS_RX` e `ABS_RY`):
   - `rx` = `ABS_RX` e `ry` = `ABS_RY`;
   - para os triggers, testa nesta ordem: `ABS_Z`/`ABS_RZ`; `ABS_BRAKE`(lt)/`ABS_GAS`(rt); `ABS_HAT2Y`/`ABS_HAT2X`.
3. **Caso B** (sem RX/RY, com Z/RZ):
   - `rx` = `ABS_Z` e `ry` = `ABS_RZ`;
   - triggers em `ABS_BRAKE`/`ABS_GAS` ou `ABS_HAT2Y`/`ABS_HAT2X`;
   - aviso `ambiguous_axis_assignment`.
4. O caso B, ou mais de um par de trigger candidato, só grava com `--accept-axis-guess`. Sem a flag, `draft_mapping` levanta `AmbiguousAxisAssignmentError`, que a CLI traduz em exit 2 listando os candidatos.
5. Faltando qualquer um de lx, ly, rx, ry, lt ou rt, termina em exit 4, listando os canais ausentes e os `ABS_*` e `BTN_TL2/TR2` detectados. Se houver `BTN_TL2/TR2` sem eixo, o motivo é `digital_triggers_only`.
6. Com `driver = hid-generic`, os botões ficam vazios (`{}`), com o aviso `face_buttons_not_positional`. O mapping v1 aceita `buttons` vazio (`mapping.py:71`).

**Lacunas declaradas:**

- Xbox via Bluetooth (`045e:0b13` etc.) e 8BitDo em modo D-input ou Switch não estão no catálogo e seguem pela heurística.
- A partir de qual versão do kernel o DS4 passou a usar hid-playstation.

### RF6 — Mapping draft (D9)

- **Range:** absinfo vence `known_ranges` do catálogo. Sem nenhum dos dois, o resultado é `ranges_unavailable:<canais>`.
- **Stick:**
  - `minimum` e `maximum` vêm do range;
  - `center` = `center_override` do catálogo, se estiver estritamente entre os limites; senão `(minimum + maximum + 1) // 2`. Exemplos: `-32768..32767` → 0; `0..255` → 128; `0..4095` → 2048;
  - pré-condição: `maximum - minimum >= 2`, senão `invalid_range:<canal>`.
- **Trigger:**
  - `rest = minimum` e `maximum = maximum` (`gamepad.rst:170`);
  - pré-condição: `maximum > rest`;
  - `minimum < 0` gera o aviso `trigger_signed_range`.
- **`provisional=true`** em todo draft. Só o wizard pode, no futuro, gravar `false`, e nenhum comando deste incremento faz isso (**P6**).
- **O que o draft não garante:**
  - que o centro seja o repouso real;
  - que o trigger em repouso fique em `minimum`;
  - que o hardware alcance o range do driver;
  - que a orientação dos eixos esteja certa (xpad e hid-nintendo invertem Y);
  - que deadzone de firmware ou calibração no driver (hid-nintendo) fiquem visíveis.
- Não existe draft parcial. Um canal sem código ou sem range resulta em `InsufficientCapabilities` e nada é gravado.
- **Saída:** `json.dumps(..., ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"`, com chaves de botão em decimal. O texto é validado por `loads_device_mapping` antes de gravar. A mesma entrada produz os mesmos bytes e o mesmo `sha256`.

### RF7 — Persistência e registry (D6, D7)

```text
~/.config/zonepad/devices/          # --devices-dir; diretórios com modo 0o700
├── index.json                      # cache; schema próprio, schema_version 1
└── <stable_id>/
    ├── mapping.json                # mapping v1 inalterado
    └── identity.json               # sidecar; schema próprio, schema_version 1
```

- **Chave (D6):** `MappingKey(stable_id, connection)`.
  - A conexão já está no token de bus do ID, então mudar entre USB e Bluetooth gera outro ID e não há fallback entre eles.
  - **Busca:** o store procura pelo `stable_id` (o diretório é a chave). A conexão gravada só é comparada quando a conexão detectada agora é diferente de `unknown`. Assim, um draft gravado com `--connection usb` num dispositivo `bus%04x` continua sendo encontrado por `run` e por `mapping show` offline. Se a conexão detectada for conhecida e divergir da gravada, o resultado é exit 2.
  - `device_version` e `firmware` diferentes do valor gravado geram os avisos `device_version_changed` e `firmware_changed`, e o mapping continua sendo usado.
- **`--connection usb|bluetooth|desconhecida`:** só substitui uma conexão detectada como `unknown`. Se divergir de uma conexão detectada, sai com exit 2. O sidecar registra `connection_source: detected | override`.
- **`identity.json`:**

```json
{
  "schema_version": 1,
  "stable_id": "usb-045e-02ea-s1a2b3c4d5e",
  "connection": "usb",
  "connection_source": "detected",
  "hardware": {
    "bustype": "0x0003", "vendor_id": "0x045e", "product_id": "0x02ea",
    "device_version": "0x0408", "firmware": null, "driver": "xpad",
    "name": "Microsoft X-Box One S pad",
    "uniq": null, "usb_serial": "SYNTH0001", "phys": "usb-0000:00:14.0-2/input0"
  },
  "identity": {"qualifier_source": "usb_serial", "occurrence": null, "fragile": false},
  "draft": {
    "catalog_entry_id": "xpad-xboxone", "catalog_version": 1, "catalog_source": "builtin",
    "range_source": "evdev_absinfo", "provisional": true,
    "provisional_fields": ["axes.lx.center", "axes.ly.center", "axes.rx.center",
                           "axes.ry.center", "triggers.lt.rest", "triggers.rt.rest"],
    "absinfo": {"0": {"minimum": -32768, "maximum": 32767, "fuzz": 16, "flat": 128,
                      "resolution": 0, "value_at_probe": 0}},
    "warnings": ["provisional_center"]
  },
  "mapping_file": "mapping.json",
  "mapping_sha256": "<64 hex>",
  "created_at": "2026-10-25T12:00:00Z",
  "app_version": "0.1.0"
}
```

  - A validação é estrita: o `stable_id` precisa ser igual ao nome do diretório e casar com a regex, e `mapping_file` é fixo.
  - O valor cru de `uniq`, serial e `phys` só existe neste arquivo local, nunca em exports, relatórios, capturas ou manifestos.
- **`index.json`:** `{"schema_version": 1, "entries": [{"stable_id", "connection", "mapping_sha256", "provisional", "fragile", "updated_at"}]}`, ordenado por `stable_id`.
- **Escrita:**
  1. valida o mapping com o parser v1;
  2. se `mapping.json` já existe e não há `--force`, sai com exit 2;
  3. grava com `write_text_atomic`, nesta ordem: `mapping.json` → `identity.json` → `index.json`.
- **Leitura:**
  - O índice é reconstruído em memória quando está ausente, inválido ou divergente dos sidecars. A reconstrução varre só subdiretórios que casam com a regex e registra `WARNING`.
  - Comandos de leitura não regravam o índice; `mapping draft` regrava.
  - O `sha256` do mapping é recalculado a cada resolução. Se divergir do sidecar, o status é `edited`: o arquivo é usado e a CLI avisa. Se falhar no parser, o status é `invalid` com o campo, sem derrubar os demais.
  - Um diretório com `mapping.json` e sem `identity.json` tem status `invalid` ("identidade ausente").
- `mapping_sha256` continua sendo o hash do arquivo usado e é repassado a `measure` e `calibrate`.

### RF8 — Precedência de mapping (D8) e compatibilidade `eventN` (D12)

Ordem de avaliação: referência do dispositivo → mapping → perfil (`run`) → abertura do nó.

| # | `--device` | `--mapping` | Mapping salvo | Resultado | Exit |
| --- | --- | --- | --- | --- | --- |
| 1 | `eventN` | válido | não é consultado | **caminho legado**, sem sysfs nem store; mesmo comportamento de hoje | o de hoje, exceto M15 |
| 2 | qualquer | inválido | qualquer | erro do parser, sem fallback para o salvo | 2 |
| 3 | `stable_id` | válido | ausente | usa o explícito | — |
| 4 | `stable_id` | válido | presente | usa o explícito; `INFO` registra igualdade ou divergência de `sha256` | — |
| 5 | `stable_id`/`eventN` | — | válido | usa o salvo; `WARNING` se `provisional` ou `edited` | — |
| 6 | `stable_id`/`eventN` | — | `invalid` | "mapping salvo inválido: <campo>; rode `zonepad mapping validate` ou `mapping draft --force`" | 2 |
| 7 | `stable_id`/`eventN` | — | ausente | "nenhum mapping para <id>; crie com `zonepad mapping draft --device <id>` ou passe `--mapping`" | 2 |
| 8 | não descoberto | qualquer | qualquer | "dispositivo <ref> não encontrado; rode `zonepad devices`" | 3 |
| 9 | base `bus-vid-pid` ambígua | qualquer | qualquer | lista os candidatos | 2 |

- `--device` aceita: `stable_id` exato, `eventN`, ou a base `<bus>-<vid>-<pid>` quando ela identifica um único gamepad.
- Fora do caminho legado, a resolução acontece antes do `open`. O backend continua recebendo `eventN` (`evdev.py:142` não muda), e `DeviceInfo.device_id` continua sendo `eventN`.
- Por isso capturas, manifestos e diretórios de sessão não mudam.
- **Verificação depois do `open`:** o scanner relê o nó aberto e compara o `input_token` (`inputM`) capturado na descoberta. Esse token nunca se repete dentro do boot (`input.c:1957`, `:1991`), então detecta até um gêmeo que assumiu o mesmo `eventN`, o que VID, PID e `uniq` sozinhos não fazem. Se o token divergir, a sessão é fechada com exit 3.
- **Conferência de range de catálogo** (mitigação de P9): quando o `identity.json` registra `range_source = catalog`, `run` e `calibrate` chamam o `AbsInfoReader` antes de construir o backend, com um `open` separado e sem tocar em `EvdevSession`. Se o range divergir, emitem o aviso `absinfo_mismatch:<canal>` em `WARNING` e seguem com o mapping salvo. Se o acesso for negado, seguem sem aviso extra, porque o `open` da sessão vai falhar logo depois com a mensagem de permissão.
- O mapping nunca vem de outro `stable_id` nem de outra conexão.

### RF9 — CLI `zonepad devices`

```text
zonepad devices [--json] [--all] [--verify] [--watch [--interval S]]
                [--sysfs-root PATH] [--devices-dir PATH]
```

- **Tabela** (stdout): colunas `ID`, `NOME`, `VID:PID`, `CONEXÃO`, `NÓ` e `MAPPING` (`salvo`, `provisório`, `editado`, `inválido` ou `ausente`).
  - Com `--all`, ganha a coluna `MOTIVO`, e o `ID` aparece como `-` quando não há identidade.
  - Avisos de fragilidade vão abaixo da tabela.
- **`--json`:** uma linha por dispositivo, gerada com `json.dumps(obj, ensure_ascii=False, sort_keys=True)`.
  - Campos estáveis: `schema_version`, `id`, `kind`, `gamepad_kind`, `name`, `vid`, `pid`, `version`, `bus`, `connection`, `node`, `mapping`, `fragile_id`, `reasons` e `warnings`. Com `--verify`, também `access`.
  - `uniq`, serial e `phys` ficam fora.
  - Ordem: gamepads por `id`; depois os demais, ordenados por `(id or "", número do nó)`.
- **`--verify`:** abre cada gamepad com `O_RDONLY|O_NONBLOCK`, fecha logo em seguida e informa `ok` ou `sem permissão`. Nunca roda por padrão e não pode ser combinado com `--watch`.
- **`--watch`:** imprime a lista e depois os eventos `added`, `removed` e `renamed` até Ctrl+C. Com `--json`, cada evento sai como `{"event": "added"|"removed"|"renamed", ...}`. O intervalo padrão é 1 s, aceito entre 0,25 e 5. Lista vazia **não** encerra o `--watch`: o caso de uso principal é esperar o controle ser plugado.
- **Exit:**
  - 0 se houver ao menos um gamepad;
  - 3 se não houver nenhum gamepad, mesmo que `--all` liste outros nós, ou se o sysfs estiver ausente ou inacessível;
  - com `--watch`, 3 só para sysfs ausente ou inacessível;
  - 2 para argumentos inválidos; 1 para falha inesperada; 130 ao interromper `--watch`.
- `zonepad list` continua byte-idêntico, e o README passa a recomendar `devices`.

### RF10 — CLI `zonepad mapping`

```text
zonepad mapping draft --device REF [--connection {usb,bluetooth,desconhecida}]
                      [--out PATH | --print] [--force] [--no-probe]
                      [--accept-fragile-id] [--accept-axis-guess]
                      [--catalog PATH] [--sysfs-root PATH] [--devices-dir PATH]
zonepad mapping show --device REF [--json] [--sysfs-root PATH] [--devices-dir PATH]
zonepad mapping validate PATH
```

- **`draft`:** descobre → resolve → lê absinfo (exceto com `--no-probe`) → aplica o catálogo → monta o draft → valida com o parser v1 → grava.
  - `--print` manda o mapping para stdout e a proveniência para stderr, sem gravar arquivo.
  - `--out` grava só o mapping, sem sidecar, e avisa que `run` não vai resolvê-lo sozinho.
  - Identidade frágil exige `--accept-fragile-id`. Com TTY, o comando pode perguntar em vez de exigir a flag. `--force` só sobrescreve um mapping existente e nunca contorna ambiguidade.
  - Sem permissão no nó, usa `known_ranges` com aviso. Sem ranges no catálogo, sai com exit 3 e a mensagem de permissão.
  - Em sucesso, imprime: `mapping provisório gravado em <path>; próximo passo: zonepad calibrate --device <id>`.
- **`show`:** com `stable_id`, funciona offline; com `eventN` ou base, faz descoberta. Mostra chave, status, proveniência, caminho e o mapping. Com `--json`, sai como `{"identity", "mapping", "status"}`.
- **`validate`:** exit 0 com resumo, ou exit 2 com `erro: [INVALID_MAPPING] <campo>: <motivo>`. O parser atual informa o primeiro erro com o caminho do campo (`mapping.py:169-172`); listar todos os erros fica fora de escopo.
- **Exit:**
  - `draft`: 0; 2 para referência ambígua, identidade frágil ou eixos ambíguos sem confirmação, mapping existente sem `--force`, `--connection` conflitante ou argumentos inválidos; 3 para dispositivo ausente, ou sem permissão e sem ranges de catálogo; 4 para canais insuficientes, família sem suporte, `ranges_unavailable` com `--no-probe` ou range inválido; 1 para falha inesperada.
  - `show`: 0; 2 para referência ambígua, mapping não salvo ou salvo inválido; 3 para dispositivo não descoberto; 1.
  - `validate`: 0; 2; 1.
- Mensagens em PT-BR, sem stack trace e com o próximo comando sugerido.

### RF11 — Integração com `run` e `calibrate`

- **`--device`:** passa a aceitar "ID estável (`zonepad devices`), nó evdev (`eventN`) ou base `<bus>-<vid>-<pid>`".
- **`--mapping`:** passa a ser opcional no parser e na execução, e vence o mapping salvo. A mensagem "--mapping é necessário" (`cli.py:279-284`) sai.
- **Novos parâmetros:** `--sysfs-root` e `--devices-dir`. `--catalog` só existe em `mapping draft`, porque `run` e `calibrate` não geram draft.
- **`run`:** os exit codes 2 e 3 seguem RF8 e M15. A ordem dos `except` muda para que `DeviceNotFoundError` e `FileNotFoundError` venham antes de `(OSError, RuntimeError)` (`cli.py:323-333`).
- **`calibrate`:** muda só a ordem no composition root, usando os efeitos que o reducer já emite (`application/calibrate.py:115-119`):
  1. Valida TTY, thresholds e durações. Com `--mapping` explícito, carrega o mapping já neste passo, como hoje.
  2. No efeito `select_device`:
     - com `--device`, resolve a referência;
     - sem `--device`, mostra só `snapshot.gamepads` como `"{name} ({stable_id}, {eventN})"`.
  3. No efeito `validate_mapping`, chama `resolve_mapping` e `load_device_mapping`. Mapping ausente ou inválido dá exit 2, antes de construir o backend.
  4. Constrói o backend com `backend_builder(mapping)`. No caminho legado, isso continua acontecendo antes, como hoje.
  5. No efeito `confirm_device`, mostra identidade, conexão e origem do mapping ("mapping salvo (provisório)" ou "--mapping <arquivo>").
  6. O resumo final sugere `zonepad run --device <stable_id> --profile <uuid>` quando o mapping veio do salvo.
- Reducer, wizard, métricas, retry, `MeasureRunner` e perfil não mudam.
- **Logs** (stderr, logger `zonepad.cli`): os campos vão na mensagem como `key=value` e também em `extra`, porque o formato padrão do `basicConfig` não mostra `extra`:
  - `INFO device resolved stable_id=… node=… reference=stable_id|event_node|base|legacy`;
  - `INFO mapping resolved source=explicit|saved path=… sha256=… provisional=…`;
  - `INFO explicit mapping overrides saved mapping stable_id=… explicit_sha256=… saved_sha256=…`;
  - `WARNING` para mapping provisório ou editado e para índice reconstruído.

### RF12 — Hot-plug (D11)

- **Implementação:** `PollingHotplugWatcher(scanner, policies, clock, interval_s)` em `application/hotplug.py`, usando a porta `Clock` existente (`application/ports.py:53-56`).
- **`snapshot()`:** retorna `DiscoverySnapshot`.
- **`poll()`:** retorna `HotplugChange(added, removed, renamed, observed_at_ns)`.
- **Comparação por `input_token` (`inputM`).** Ele nunca se repete dentro de um boot (`input.c:1957`, `:1991-1992`); o `eventN` pode se repetir.
  - Token novo → `added`; token que sumiu → `removed`.
  - **Reconexão:** o mesmo `stable_id` volta com outro token e aparece como `removed` do token antigo seguido de `added` do novo.
  - **Renumeração em grupo frágil:** quando um membro de um grupo `n<k>` ou `.k` sai, os nós que continuam mantêm o token mas podem trocar de ID. O watcher emite `removed` do nó que saiu e `renamed(old_id, new_id)` para cada nó que continua com ID diferente.
- **Nós auxiliares** (touchpad, IMU, nós sintéticos) não geram eventos na saída padrão.
- **`follow(watcher, clock, interval_s, should_stop)`:** chama `clock.sleep(interval_s)` entre polls e emite só mudanças não vazias.
- **`calibrate`:** usa um snapshot único na tela de escolha, porque `ask_choice` é bloqueante.
- Reconexão do runtime fica fora. A desconexão em execução continua sendo `DeviceDisconnectedError` (`evdev.py:68-74`).

### RF13 — Permissões (D13)

- **FATO:** os atributos de input no sysfs são `S_IRUGO` (`input.c:1343`, `:1463`, `:1477`, `:1537`, `:1597`).
- **FATO:** a regra udev padrão põe o nó no grupo `input` (`systemd rules.d/50-udev-default.rules.in:51`); joysticks recebem `uaccess` (`70-uaccess.rules.in:73`).
- **INFERÊNCIA:** um usuário com sessão local ativa costuma ter ACL no nó.
- **Mensagem para acesso negado ao nó:**

  > Sem permissão de leitura em /dev/input/event7 (controle `<id>`).
  > 1. Verifique com `ls -l /dev/input/event7` e `getfacl /dev/input/event7`. Numa sessão gráfica local, o acesso costuma vir por ACL (uaccess).
  > 2. Alternativa: `sudo usermod -aG input "$USER"` e reiniciar a sessão. Impacto: o grupo `input` dá leitura de **todos** os dispositivos de entrada, inclusive o teclado. Para desfazer: `sudo gpasswd -d "$USER" input` e reiniciar a sessão.
  > Enquanto isso, `zonepad mapping draft --no-probe` usa só o catálogo (famílias conhecidas).

- O ZonaPad nunca executa `sudo`, nunca altera ACL, udev ou `chmod`, e nunca sugere `chmod` em `/dev/input`.

## Requisitos não funcionais

- Python 3.15.0, stdlib apenas (`fcntl`, `struct`, `ctypes`, `hashlib`, `json`). Nenhuma dependência nova.
- `domain/` não importa `os`, `pathlib`, `time`, `evdev`, `subprocess`, `fcntl`, `select` nem `struct`. `application/` não importa `zonepad.infrastructure`.
- APIs públicas tipadas, com `ruff` e `mypy src/zonepad` limpos.
- Saídas determinísticas: a mesma fixture gera a mesma tabela, o mesmo JSON e os mesmos bytes de mapping.
- Nenhum `print` fora da camada de interface; logging estruturado.
- Custo do polling: cerca de 15 leituras pequenas por nó novo, com cache por `(event_node, input_token)`.

## Modelo de dados e unidades

- Os valores de eixo e trigger são **counts do dispositivo** (inteiros com sinal de 32 bits do evdev) e não têm unidade física.
- `center` e `rest` são counts declarados (provisórios). `fuzz` e `flat` são counts.
- `resolution` segue `input.h:81-91`: unidades/mm para `ABS_X/Y/Z` e MT; unidades/rad para `ABS_RX/RY/RZ`; unidades/g e unidades/(°/s) quando `INPUT_PROP_ACCELEROMETER` está ligado. Em gamepads costuma ser 0. Fica só como diagnóstico.
- O input core **não limita** os valores reportados a `[minimum, maximum]` (`input.h:78-79`). O clamp da normalização existente cobre isso.

### Tipos de domínio (todos `@dataclass(frozen=True, slots=True)`)

```python
# domain/discovery.py
class DeviceClass(StrEnum): GAMEPAD; KEYBOARD; MOUSE; TOUCHPAD; MOTION_SENSOR; VIRTUAL; UNKNOWN
class GamepadKind(StrEnum): GAMEPAD; JOYSTICK_HID
AbsInfo(minimum: int, maximum: int, fuzz: int, flat: int, resolution: int, value_at_probe: int | None)
AxisCapability(code: int, absinfo: AbsInfo | None)
ButtonCapability(code: int)
DeviceCapabilities(event_types, axes: tuple[AxisCapability, ...], buttons: tuple[ButtonCapability, ...],
                   relative_axes, properties)
ObservedInputDevice(event_node: str, input_token: str | None, sysfs_path: str | None, name: str | None,
                    bustype, vendor_id, product_id, version: int | None, uniq, phys, usb_serial: str | None,
                    driver: str | None, firmware: str | None, usb_interface_protocol: str | None,
                    is_virtual_path: bool, capabilities: DeviceCapabilities | None,
                    issues: tuple[ReadIssue, ...])
Verdict(device_class: DeviceClass, gamepad_kind: GamepadKind | None, reasons: tuple[str, ...],
        warnings: tuple[str, ...])
def classify(device: ObservedInputDevice, policy: GamepadFilterPolicy) -> Verdict
DiscoveredDevice(observed: ObservedInputDevice, verdict: Verdict, identity: StableIdentity | None)
DiscoverySnapshot(devices: tuple[DiscoveredDevice, ...])  # .gamepads
HotplugChange(added: tuple[DiscoveredDevice, ...], removed: tuple[DiscoveredDevice, ...],
              renamed: tuple[tuple[StableId, StableId], ...], observed_at_ns: int)
def diff_snapshots(before, after, at_ns) -> HotplugChange

# domain/identity.py
class Connection(StrEnum): USB = "usb"; BLUETOOTH = "bluetooth"; UNKNOWN = "unknown"
class QualifierSource(StrEnum): UNIQ; USB_SERIAL; PHYS; OCCURRENCE
HardwareFacts(bustype, vendor_id, product_id, device_version, firmware, driver, name, uniq, usb_serial, phys)
StableIdentity(stable_id: StableId, facts: HardwareFacts, connection: Connection,
               qualifier_source: QualifierSource, occurrence: int | None, fragile: bool)
MappingKey(stable_id: StableId, connection: Connection)
def parse_stable_id(text: str) -> StableId
def derive_stable_ids(devices: Sequence[tuple[str, HardwareFacts]], policy: IdentityPolicy) -> Mapping[str, StableIdentity]

# domain/catalog.py
CatalogEntry(...)  # campos de RF5
CatalogMatch(entry: CatalogEntry | None, catalog_version: int, source: Literal["user", "builtin", "generic"])

# domain/mapping_draft.py
AxisDraft(code, minimum, center, maximum, range_source, center_source)
TriggerDraft(code, rest, maximum, range_source, rest_source)
DraftProvenance(catalog_entry_id, catalog_version, catalog_source, provisional, provisional_fields, warnings)
MappingDraft(axes, triggers, buttons: Mapping[int, str], provenance, axis_candidates: tuple[str, ...])
InsufficientCapabilities(missing_channels, detected_axes, detected_buttons, reason)
DraftRules(stick_channels, trigger_candidates: tuple[tuple[int, int], ...], right_stick_fallback: tuple[int, int],
           min_stick_span: int)  # D9/D10 como dados
def build_draft(capabilities, catalog: CatalogMatch, rules: DraftRules) -> MappingDraft | InsufficientCapabilities

# domain/identity.py (políticas)
IdentityPolicy(bus_tokens: Mapping[int, str], bus_connections: Mapping[int, Connection],
               mac_pattern: re.Pattern[str], placeholder_pattern: re.Pattern[str])
GamepadFilterPolicy(...)  # códigos e faixas de RF2
```

DTOs de aplicação:

```python
StoredMappingRef(key: MappingKey, mapping_path: str, mapping_sha256: str, recorded_sha256: str,
                 provisional: bool | None, range_source: str | None,
                 status: Literal["saved", "provisional", "edited", "invalid"], detail: str | None)
MappingRecord(key: MappingKey, identity: StableIdentity, connection_source: Literal["detected", "override"],
              mapping_text: str, provenance: DraftProvenance, absinfo: Mapping[int, AbsInfo],
              created_at: str, app_version: str)
```

`draft_mapping` levanta `AmbiguousAxisAssignmentError(candidates)` quando `axis_candidates` não está vazio e não há confirmação.

As constantes Linux (códigos, bus tokens, critérios D2, D3 e D9) ficam num único módulo de infraestrutura, `infrastructure/linux_input_policy.py`. Esse módulo monta `GamepadFilterPolicy`, `IdentityPolicy` e `DraftRules`. O domínio recebe essas políticas como dados.

Erros novos (aditivos em `domain/errors.py`): `AmbiguousDeviceError(reference, candidates)`, `AmbiguousAxisAssignmentError(candidates)`, `DeviceAccessDeniedError(event_node)`, `MappingNotFoundError(key)` e `MappingConflictError`. `DeviceNotFoundError` é reaproveitado.

### Portas (aditivas em `application/ports.py`)

```python
class InputDeviceScanner(Protocol):
    def scan(self) -> Sequence[ObservedInputDevice]: ...          # nunca abre /dev; DeviceNotFoundError se a raiz falta

class AbsInfoReader(Protocol):
    def read_absinfo(self, event_node: str, codes: Sequence[int]) -> Mapping[int, AbsInfo]: ...
    # DeviceAccessDeniedError | DeviceNotFoundError

class DeviceCatalog(Protocol):
    def match(self, observed: ObservedInputDevice) -> CatalogMatch: ...

class DeviceMappingStore(Protocol):
    def find(self, key: MappingKey) -> StoredMappingRef | None: ...
    def save(self, record: MappingRecord, *, overwrite: bool) -> StoredMappingRef: ...
    def entries(self) -> Sequence[StoredMappingRef]: ...

class HotplugWatcher(Protocol):
    def snapshot(self) -> DiscoverySnapshot: ...
    def poll(self) -> HotplugChange: ...
```

Casos de uso (`application/`): `discover_devices`, `resolve_device_reference`, `draft_mapping` e `resolve_mapping`. `resolve_mapping` devolve `ResolvedMappingRef(source, path, sha256, provisional, overridden_saved)`. A composição carrega o `DeviceMapping` com `load_device_mapping(path)`, mantendo a validação estrita atual.

## Impacto por camada

| Camada | Novo | Alterado (aditivo) | Inalterado |
| --- | --- | --- | --- |
| domain | `discovery.py`, `identity.py`, `catalog.py`, `mapping_draft.py` | `errors.py` | `device.py` (`DeviceInfo`), `profile.py`, métricas |
| application | `discovery.py`, `mapping_draft.py`, `mapping_resolution.py`, `hotplug.py` | `ports.py` | `calibrate.py` (reducer), `measure.py`, `runtime.py` |
| infrastructure | `sysfs.py`, `absinfo.py`, `catalog.py` + `catalog_data/families.json`, `device_store.py`, `linux_input_policy.py` | `mapping.py` (`loads_device_mapping`, `dumps_device_mapping`; schema intacto) | `evdev.py`, `uinput.py`, `capture_writer.py` |
| interface | `device_cli.py` | `cli.py` (subcomandos, `run`, `CliDependencies` injetáveis), `calibration_cli.py` (ordem no composition root) | ramo `list` |
| packaging | — | `pyproject.toml` (`package-data` do catálogo) | dependências |

`DeviceInfo` fica intacto. O nome `DeviceIdentity` já existe em `domain/profile.py:221`, por isso o tipo novo se chama `StableIdentity`.

## Impacto em hardware/dispositivos

- Leitura do sysfs sem privilégio. Abertura do nó só em `mapping draft` (para o ioctl), `devices --verify`, `run` e `calibrate`.
- Famílias cobertas pelo catálogo: Xbox 360, 360W e One/Series via xpad, 8BitDo em X-input, DS4 e DualSense. O Switch Pro é reconhecido, mas termina em exit 4 (triggers digitais, **P4**).
- HID genérico só gera draft com absinfo e confirmação de eixos quando houver ambiguidade.
- **Lacunas para o smoke com hardware** (etapa 13, só com autorização):
  - se controles Xbox publicam `serial` USB;
  - `uniq`/`phys` no Bluetooth via BlueZ/uhid;
  - eixos do Xbox via Bluetooth;
  - 8BitDo em modo D-input;
  - nomes de dispositivo por tipo de conexão.
- **Critério de aceite do smoke:**
  - registrar `bustype/vid/pid/version`, driver, bitmaps e o absinfo de cada canal, com `uniq` e serial anonimizados;
  - tolerância: ranges **idênticos** aos de `known_ranges`; qualquer divergência é bug do catálogo ou do kernel e vira issue;
  - marcar `verified_on_hardware = true` só depois dessa comparação, registrando a versão do kernel e a data.

## Plano de testes

Todos os testes usam `pytest`, `tmp_path`, fakes e `CliDependencies`. Nenhum acessa `/sys`, `/dev/input`, `/dev/uinput`, TTY real ou rede.

- **Fixtures:**
  - o builder `tests/sysfs_builder.py` gera em `tmp_path` a árvore `class/input/eventN -> ../../devices/.../inputM/eventN` com symlinks relativos;
  - `tests/fixtures/sysfs/` é uma árvore versionada mínima para o smoke;
  - a permissão negada é simulada com `read_text` injetado (sem `chmod`, que não tem efeito como root);
  - o absinfo vem de `FakeAbsInfoReader`.
- **Confinamento:**
  - um audit hook (`sys.addaudithook`) em `tests/conftest.py` fica ativo só por meio de um `ContextVar` dentro do fixture `forbid_io_outside(root)`;
  - ele captura `open`, `os.open`, `Path.read_text`, `os.scandir` e `fcntl.ioctl`, comportamento verificado no 3.15.0;
  - todo caminho precisa estar sob a raiz depois de `realpath`, e qualquer `ioctl` falha o teste.
- **Arquitetura:** `tests/test_architecture.py` analisa com `ast` os imports proibidos em `domain/` e o acesso de `application/` a `infrastructure`.

Os dados sintéticos das fixtures seguem duas regras:

- MAC com o bit *locally administered* (`02:...`);
- seriais com o prefixo `SYNTH`.

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Xbox One S USB | xpad, `045e:02ea`, `serial=SYNTH0001`, absinfo fake | `gamepad`; ID `usb-045e-02ea-s<hash>`; draft com sticks `{-32768, 0, 32767}`, triggers `{0, 1023}`, botões 304/305/307/308 |
| Xbox sem serial | mesmo fixture sem `serial` | `source=phys`, aviso `identity_bound_to_port` |
| DualSense BT | gamepad + touchpad + motion com o mesmo `uniq` | 1 gamepad (`connection=bluetooth`, `source=uniq`); touchpad e motion só em `--all` |
| MAC com caixa diferente | `uniq` em minúsculas e em maiúsculas | mesmo qualificador |
| Teclado | bloco completo de teclas, sem ABS | `keyboard`, oculto por padrão |
| Mouse | `REL_X/Y` + `BTN_LEFT` | `mouse` |
| Touchpad | `INPUT_PROP_POINTER` + `ABS_MT_POSITION_X/Y` | `touchpad` |
| Virtual do ZonaPad | `devices/virtual/input`, `1234:0001`, `BUS_USB` | `virtual`, `virtual:zonapad`, não selecionável |
| Virtual genérico | `devices/virtual/input`, nome Xbox | `virtual:uinput` |
| BT via uhid | caminho `devices/virtual/misc/uhid/...` | `gamepad` (não `virtual`) |
| Symlink quebrado | `device` → inexistente | `unknown`, `broken_device_link`; a varredura continua |
| Sem permissão | `read_text` levanta `PermissionError` | `permission_denied`; exit 3 só se não sobrar nenhum gamepad |
| 360W com 2 pads | mesmo `phys`, sem `uniq` e sem `serial` | `...-p<hash>` e `...-p<hash>.2`, ambos `fragile`, com aviso |
| Gêmeos sem qualificador | 2 nós iguais, sem `uniq`, `serial` ou `phys` | `...-n1` e `...-n2`, determinísticos; `event2` < `event10` |
| Bitmap W=32 | mesmo Xbox com palavras de 32 bits | mesmo resultado de W=64 |
| Range 0..4095 | HID genérico com absinfo fake | draft com range real e `center 2048` |
| Sem trigger | HID genérico sem par de trigger | exit 4; lista lt, rt e os ABS detectados; nenhum arquivo gravado |
| Switch Pro | `nintendo`, `BTN_TL2/TR2` | exit 4, `digital_triggers_only` |
| Caso B ambíguo | sem RX/RY, com Z/RZ | exit 2 sem `--accept-axis-guess`; grava com a flag |
| Catálogo diverge | absinfo diferente de `known_ranges` | usa o absinfo e emite aviso `catalog_range_mismatch` |
| `--no-probe` | família catalogada, depois genérico | ranges do catálogo; genérico termina em exit 4 `ranges_unavailable` |
| Absinfo negado | o reader levanta `DeviceAccessDeniedError` | família catalogada usa o catálogo; genérico termina em exit 3 com a mensagem de permissão |
| Ioctl | `opener`/`ioctl` fake | número `0x80184540 + code`; `close` mesmo em erro; nenhum `read` |
| Determinismo | mesma fixture, duas execuções | arquivos byte-idênticos, mesmo `sha256` |
| Mapping existente | já salvo | exit 2 sem `--force`; `--force` sobrescreve de forma atômica |
| `--print` | draft | nada gravado em disco |
| Identidade frágil | `n1` sem `--accept-fragile-id` | exit 2, lista os gêmeos |
| Índice | ausente, corrompido, órfão ou com `sha` divergente | reconstruído; leitura não regrava o índice |
| Mapping editado | `sha` diferente do sidecar | status `edited`, com aviso |
| `stable_id` malicioso | diretório `../x` ou ID fora da regex | rejeitado |
| `validate` | JSON com campo desconhecido | exit 2, com o campo informado |
| Precedência | tabela RF8 parametrizada | todos os casos |
| `run` com ID estável | mapping salvo | o backend fake recebe o mesmo `DeviceMapping` que um `--mapping` equivalente |
| Explícito vence salvo | salvo + `--mapping` diferente | usa o explícito; `caplog` registra a divergência |
| Compat `eventN` | `run --device event3 --mapping m.json` | mesmo `open("event3")` e mesmo mapping que hoje |
| Dispositivo ausente | ID desconhecido | exit 3 com mensagem acionável |
| Reatribuição de nó | fatos mudam entre descoberta e `open` | exit 3 |
| `calibrate` sem `--mapping` | mapping salvo | lista só gamepads e confirma identidade, conexão e origem |
| `calibrate` sem mapping salvo | — | exit 2 antes de construir o backend |
| Hot-plug | snapshots roteirizados + `FakeClock` | `added`/`removed` com ID correto; reconexão com outro `inputM` = `removed` + `added`; sem `sleep` real |
| `--watch` | `KeyboardInterrupt` | exit 130 |
| Regressão | golden de `list`; smoke de `replay`, `profiles`, `measure`, `--help` | saída de `list` byte-idêntica; suíte atual verde |

Casos adicionais apontados na revisão cruzada:

| Caso | Entrada | Esperado |
| --- | --- | --- |
| `--verify` | opener fake com `ok` e `PermissionError` | coluna `ACESSO` correta; `--verify --watch` → exit 2 |
| `--connection` | `bus0019` com `--connection usb`, depois `run` | o draft grava `connection_source=override` e o `run` encontra o mapping; `--connection bluetooth` em dispositivo `usb` → exit 2 |
| Golden `devices --json` | fixture Xbox | linha JSON idêntica, campo a campo |
| `mapping show` | offline por `stable_id`, via `eventN`, `--json` | os três caminhos com a mesma identidade |
| Nó do probe | `EvdevAbsInfoReader` com opener fake | o draft abre exatamente o nó resolvido, e nenhum outro |
| Catálogo | campo desconhecido; `--catalog` sobrepondo o embutido; carga por `importlib.resources` | loader estrito, precedência correta, package data presente |
| Artefatos de sessão | `calibrate --device <stable_id>` com sessão fake | `RawFrame.device_id`, captura e manifesto continuam com `eventN` |
| Smoke versionado | `tests/fixtures/sysfs` | a mesma descoberta documentada no README |
| Renumeração de gêmeos | `n1` sai e `n2` continua | `removed` do token que saiu + `renamed(n2 → n1)` |
| Índice reconstruído | índice corrompido | `WARNING` registrado em `caplog` |
| Range de catálogo divergente | `range_source=catalog` e absinfo fake diferente em `run` | `WARNING absinfo_mismatch:<canal>`; execução continua |
| absinfo negativo | `fuzz=-1` | aviso `absinfo_negative_field:fuzz`; dispositivo segue como gamepad |

**Teste existente alterado:** só `tests/test_runtime_cli.py:218-228`, que hoje exige a mensagem "--mapping é necessário". Ele passa a exigir exit 2 com a orientação de `zonepad mapping draft`. Os testes de `calibrate` atuais (`event3` + mapping explícito) continuam como estão.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Sysfs varia entre kernels e drivers | campo ausente ou formato diferente | leitura tolerante por campo; motivo explícito; fixtures com variantes, incluindo W=32 |
| Filtro exclui um gamepad legítimo | o controle não aparece | regras D2 com evidência; `--all` sempre disponível; motivo por candidato |
| Mapping aplicado ao gêmeo errado | calibração no controle errado | `n<k>` e `.k` com `fragile`, confirmação obrigatória, aviso e verificação depois do `open` |
| `uniq` muda ao reparear o Bluetooth (BlueZ/uhid) | ID muda | hierarquia documentada; LACUNA para o smoke |
| Centro e repouso provisórios | métricas distorcidas se a pessoa pular a calibração | `provisional=true`, aviso na CLI, README explícito e recomendação de `calibrate` |
| `fuzz` do kernel esconde ruído | ruído subestimado | `fuzz` e `flat` registrados no sidecar; risco anotado para o `calibrate` |
| Permissão no nó | o draft genérico falha | ioctl só no nó resolvido; fallback ao catálogo; mensagem com impacto e reversão |
| Catálogo desatualizado | códigos ou ranges errados | absinfo vence; match por driver; `verified_on_hardware`; revisão do `controller-hardware` |
| TOCTOU entre descoberta e `open` | nó trocado | verificação depois do `open` |
| Dado pessoal (serial ou MAC) | vazamento; o hash de um MAC é reversível por força bruta (cerca de 2^24 candidatos com o OUI) | qualificador em hash (pseudônimo, não anônimo); valor cru só no sidecar local, com diretório 0o700; README avisa que `stable_id` não deve ser compartilhado como dado anônimo (P3) |
| Escopo crescente | o incremento não fecha | sem reconexão do runtime, sem GUI e sem atualização ao vivo no `calibrate` |
| Audit hook global nos testes | interferência entre testes | `ContextVar` mais registro e `assert` no teardown |

## Critérios de aceite

Valem os critérios do prompt 04, com as mudanças M1–M16. Em resumo:

- [ ] `zonepad devices` lista só gamepads; `--all` mostra as demais classes com o motivo.
- [ ] A descoberta funciona com `--sysfs-root` apontando para fixtures (raiz `/sys`), sem `/sys` real.
- [ ] O ID estável casa com `STABLE_ID_PATTERN`, não contém `eventN` e é o mesmo em duas execuções.
- [ ] Gêmeos recebem IDs distintos, determinísticos, `fragile` e com aviso.
- [ ] `devices` não abre nenhum arquivo fora de `--sysfs-root` (audit hook). `mapping draft` só abre o nó resolvido para `EVIOCGABS`, e com `--no-probe` não abre nenhum.
- [ ] O controle virtual do ZonaPad nunca aparece como gamepad.
- [ ] `mapping draft` gera um arquivo aceito por `load_device_mapping`, byte-idêntico entre execuções.
- [ ] Mapping existente não é sobrescrito sem `--force`; `--print` não grava.
- [ ] Capabilities insuficientes dão exit 4, listam os canais ausentes e não gravam nada.
- [ ] `identity.json` registra `provisional=true` e a origem de cada range.
- [ ] `mapping show` e `mapping validate` mostram o campo do erro, sem stack trace.
- [ ] `run --device <stable_id> --profile <uuid>` resolve o mapping salvo e se comporta como um `--mapping` equivalente.
- [ ] `run --device eventN --mapping <path>` mantém o mesmo comportamento, exceto pelo exit 3 de M15.
- [ ] `--mapping` explícito vence o salvo e a divergência aparece em `INFO`.
- [ ] `calibrate --device <stable_id>` funciona sem `--mapping` e confirma identidade, conexão e origem.
- [ ] Dispositivo ausente dá exit 3; referência ambígua dá exit 2 com a lista de candidatos.
- [ ] `zonepad list` fica byte-idêntico, e há regressão para `list`, `run`, `measure`, `replay`, `profiles` e `calibrate`.
- [ ] O watcher detecta adição, remoção e reconexão sem `sleep` real.
- [ ] `pytest`, `ruff check`, `ruff format --check`, `mypy src/zonepad` e `sync_ai_assets.py --check` limpos.
- [ ] Spec, ADR 0006 e README atualizados, com exemplos copiáveis.

## Decisões P1–P9 (aprovadas com as recomendações em 2026-10-25)

| ID | Decisão | Recomendação | Alternativa |
| --- | --- | --- | --- |
| **P1** | Fonte de ranges do draft | `mapping draft` abre o nó resolvido só para `EVIOCGABS` (sem `read`), com fallback ao catálogo e `--no-probe` | Só catálogo: genérico sempre termina em exit 4, e o caso "range 0..4095" só existe no fake |
| **P2** | Semântica de `--sysfs-root` | ponto de montagem (`/sys`) | `/sys/class/input`, como no prompt: o confinamento fica impossível, porque os symlinks saem da raiz |
| **P3** | Qualificador do ID | SHA-256 sem sal (`u`/`s`/`p` + 10 hex), declarado como pseudonimização | (a) HMAC com sal local em `~/.config/zonepad`: mais privado, mas os IDs ficam presos à instalação e perder o sal órfã todos os mappings; (b) `uniq`/serial legível, como no exemplo do prompt |
| **P4** | Switch Pro (ZL/ZR digitais) | exit 4 `digital_triggers_only` neste incremento; documentar | Abrir schema v2 com triggers digitais (fora de escopo) |
| **P5** | `run` com dispositivo ausente | exit 3, como em `calibrate` | manter exit 2 |
| **P6** | Status `salvo` (não provisório) | fica inalcançável neste incremento; documentado | criar `mapping adopt` agora |
| **P7** | Override de catálogo pelo usuário | `--catalog PATH` com o mesmo schema estrito | só `--mapping` manual |
| **P8** | VID/PID reais em `DeviceInfo`, manifesto e perfil | adiar, porque mudaria artefatos do wizard | incluir agora |
| **P9** | Conferir absinfo em `run`/`calibrate` | incluir só a conferência quando `range_source = catalog`, com `open` separado antes do backend e aviso `absinfo_mismatch` (RF8); adiar a conferência sempre-ligada dentro de `EvdevSession` | conferência completa agora; ou nada, aceitando o risco de erro de catálogo silencioso |

## Decisões D1–D14

| ID | Dono | Decisão fechada |
| --- | --- | --- |
| D1 | hardware | Sysfs para descoberta, identidade e filtro; ranges por `AbsInfoReader` (`EVIOCGABS`) ou catálogo (M1, M2, P1) |
| D2 | hardware | RF2: 7 classes, regras ordenadas e motivos estáveis (M8–M10) |
| D3 | hardware | `uniq > usb_serial > phys (USB) > ocorrência`; `name` e `eventN` ficam fora (M4) |
| D4 | python | `<bus>-<vid>-<pid>-<qualificador>[.n]`, qualificador em hash, regex com até 33 caracteres (M5, M6, P3) |
| D5 | hardware | Duplicado = tupla completa; ordem numérica de `eventN`; `fragile` com confirmação (M7) |
| D6 | python | `MappingKey(stable_id, connection)`; firmware e `device_version` só geram aviso (M11) |
| D7 | python | `devices/<id>/{mapping.json, identity.json}` + `index.json` como cache; mapping v1 intacto |
| D8 | python | `--mapping` > salvo da chave > erro (RF8) |
| D9 | hardware | `center = (min+max+1)//2` ou override; `rest = min`; `provisional=true` sempre |
| D10 | hardware | Catálogo JSON v1 com match por driver e VID:PID; absinfo vence; heurística genérica com confirmação |
| D11 | python | Polling de 1 s em sysfs com `Clock` injetado; reconexão por `inputM`; sem dependência nova |
| D12 | python | `eventN` + `--mapping` = caminho legado; `list` inalterado; `devices` é o comando novo |
| D13 | hardware | Sysfs sem privilégio; nó com uaccess ou grupo `input`; mensagem com impacto e reversão |
| D14 | python | Raiz sysfs, reader, store, clock e catálogo injetáveis; audit hook; builder em `tmp_path` |
