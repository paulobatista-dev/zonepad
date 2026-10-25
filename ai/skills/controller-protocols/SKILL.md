---
name: controller-protocols
description: Orienta descoberta, identificação e leitura de controles via SDL3, HIDAPI, evdev/hidraw, XInput/Raw Input e GameController/IOKit. Use ao integrar um dispositivo, interpretar relatórios ou diagnosticar diferenças entre plataformas.
metadata:
  owner: controller-hardware
  version: "1.0"
---

# Controller Protocols

## Quando usar

Use esta skill para:

- escolher o backend de um dispositivo ou plataforma;
- identificar um controle de forma estável;
- interpretar relatórios HID e mapear eixos/triggers/botões;
- diagnosticar diferenças entre Linux, Windows e macOS;
- planejar hot-plug, permissões e captura/replay.

Não use para definir métricas de calibração; consulte `calibration-metrics`.

## Backends

| Backend | Melhor para | Vantagens | Cuidados |
| --- | --- | --- | --- |
| SDL3 Gamepad | Abstração multiplataforma | Mapeamento padronizado, hot-plug, sensores, rumble | Pode normalizar/esconder detalhes; confirme o mapping real |
| HIDAPI | Relatórios raw multiplataforma | Controle total do report, funciona em desktop | Você implementa parsing, identidade e hot-plug |
| Linux evdev | Integração nativa | Eventos, ABS, force feedback, udev | Permissões, ranges por device, não é raw HID |
| Linux hidraw | Protocolo raw no Linux | Acesso ao report original | Requer udev/permissões; não funciona em todo device |
| Windows XInput | Controles Xbox-compatíveis | API estável, rumble, até 4 controles | Mapping fixo, sem detalhes raw, triggers combinados |
| Windows Raw Input | HID genérico | Ampla cobertura, dados raw | Parsing manual, foco/janela, dispositivos variados |
| macOS GameController | Integração nativa | Perfis, haptics, Bluetooth | Requer entitlements/permissões; menos controle raw |
| macOS IOKit/HID | Protocolo raw | Detalhe total | Complexidade e permissões |

Estratégia recomendada: SDL3 como backend principal, com um adaptador raw (HIDAPI ou específico) quando a calibração exigir counts originais. Mantenha o mesmo contrato `DeviceBackend` para todos.

## Identidade do dispositivo

Colete o máximo possível:

- `vid` e `pid` em hexadecimal;
- nome do produto e fabricante;
- GUID de gamepad do SDL, quando disponível;
- path HID/evdev;
- serial, se exposto;
- versão de firmware, se exposta.

Regras:

- Não use o índice da porta como identidade; ele muda.
- Prefira uma combinação estável: `vid:pid` + serial/GUID + nome.
- Se dois dispositivos idênticos não tiverem serial, avise o usuário e permita escolher.
- Normalize o ID e registre a origem (SDL/HID/evdev).

## Parsing de relatórios

Checklist antes de escrever o parser:

1. Capture o relatório com o dispositivo em repouso, nos extremos e em transições.
2. Identifique report ID, tamanho fixo e campos.
3. Determine a ordem dos bytes (little/big endian).
4. Determine se os eixos são signed/unsigned, 8/16 bits, centrados ou não.
5. Identifique triggers analógicos e se compartilham bytes/bits.
6. Identifique hat switch e botões.
7. Valide o tamanho antes de indexar; descarte relatórios truncados.
8. Trate valores de repouso e saturação como dados, não como constantes universais.

Nunca copie offsets de um modelo para outro sem confirmar. Mesmo dispositivos do mesmo modelo podem variar por firmware.

## Plataformas

### Linux

- `evdev`: leia `/dev/input/event*`; ABS ranges vêm do dispositivo. Permissões via grupo `input` ou regra udev.
- `hidraw`: leia `/dev/hidraw*`; requer udev; útil para reports raw.
- Steam Input pode criar um device virtual e esconder o físico; documente.
- Hot-plug: monitore udev ou faça rescan periódico.
- Force feedback: não presuma suporte; verifique capabilities.

### Windows

- XInput: mapping fixo, triggers combinados em um eixo; não serve para calibrar triggers separados.
- Raw Input: melhor para HID genérico; requer janela/foco e parsing.
- DirectInput é legado; prefira XInput/Raw Input quando possível.
- Controles podem ser exclusivos; trate falha de abertura.

### macOS

- GameController framework: bom para perfis e Bluetooth; requer permissões/entitlements.
- IOKit/HID: raw, mas mais complexo.
- Bluetooth pode adicionar latência e reconexão; trate eventos de desconexão.

## Hot-plug e desconexão

- Separe "timeout sem evento" de "dispositivo desconectado".
- Faça rescan com debounce; evite abrir/fechar em loop.
- Ao reconectar, revalide identidade e capabilities.
- Preserve o perfil pelo ID estável, não pelo path.
- Registre eventos de conexão/desconexão no log.

## Captura e replay

Formato sugerido: JSONL com uma linha de metadata e uma linha por frame.

```json
{"type":"meta","schema_version":1,"device":{"vid":"0x054c","pid":"0x0ce6","name":"DualSense"},"backend":"hidapi","sample_rate_hz":250,"units":"raw"}
{"type":"frame","t_ns":123456789,"axes":{"lx":128,"ly":127,"rx":130,"ry":126},"triggers":{"l2":0,"r2":0},"buttons":["south"]}
```

Regras:

- Timestamp monotônico em nanossegundos.
- Preserve os valores raw; normalização é derivada.
- Anonimize serial, path e qualquer dado pessoal.
- Inclua a versão do capturador e o backend.
- Replay deve produzir exatamente a mesma sequência de frames.

## Checklist

- [ ] O backend foi escolhido com justificativa.
- [ ] A identidade é estável e não depende da porta.
- [ ] O parser valida tamanho e ranges.
- [ ] O repouso foi capturado, não assumido.
- [ ] Triggers e sticks têm tratamento separado.
- [ ] Permissões e hot-plug foram considerados.
- [ ] Há captura/replay para reproduzir o comportamento.
- [ ] Quirks de plataforma estão documentados.
