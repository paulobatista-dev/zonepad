---
name: calibration-metrics
description: Define métricas de calibração de sticks e triggers, incluindo repouso, drift, ruído, range, deadzone, circularidade, linearidade e histerese. Use ao medir um controle, definir critérios de aceite ou interpretar uma captura.
metadata:
  owner: controller-hardware
  version: "1.0"
---

# Calibration Metrics

## Quando usar

Use esta skill para:

- definir o protocolo de captura de um controle;
- calcular ou revisar métricas de calibração;
- estabelecer critérios de aceite por classe de dispositivo;
- comparar unidades, firmwares ou plataformas;
- diagnosticar drift, ruído, deadzone excessiva ou trigger não linear.

Não use para decidir o parser HID; consulte `controller-protocols`.

## Camadas e unidades

| Camada | Stick | Trigger | Uso |
| --- | --- | --- | --- |
| Raw | counts do dispositivo | counts do dispositivo | Diagnóstico e replay |
| Normalizado | [-1, 1] por eixo | [0, 1] | Métricas comparáveis |
| Calibrado | [-1, 1] após perfil | [0, 1] após perfil | Comportamento final |

Toda métrica deve declarar a camada e a unidade. Não compare números de camadas diferentes.

## Métricas

| Métrica | Definição | Como calcular |
| --- | --- | --- |
| Centro de repouso | Posição média em repouso | Mediana de N amostras por eixo |
| Drift | Desvio máximo do centro ao longo do tempo | `max(||p(t) - c||)` em repouso |
| Ruído RMS | Energia do ruído em repouso | `sqrt(mean(||p(t) - c||²))` |
| Ruído pico-a-pico | Amplitude do ruído | `max - min` por eixo |
| Range | Curso útil do eixo | `max - min` normalizado |
| Simetria | Equilíbrio em torno do centro | `(max - c) / (c - min)` |
| Raio de ruído | Máxima excursão de repouso | `max(||p(t) - c||)` |
| Deadzone recomendada | Limiar para zerar ruído | `max(raio_de_ruido * fator, mínimo)` |
| Circularidade | Quão circular é o gate | `min(r) / max(r)` no movimento circular |
| Raio médio | Tamanho efetivo do gate | `mean(r)` no movimento circular |
| Linearidade do trigger | Aderência a uma reta | `R²` e erro absoluto máximo |
| Histerese | Diferença subida/descida | `max(|y_up(x) - y_down(x)|)` |
| Jitter | Variação entre amostras vizinhas | `mean(|Δp|)` e `max(|Δp|)` |
| Taxa efetiva | Frequência real de amostras | `1 / mean(Δt)` |
| Saturação | Tempo nos extremos | Proporção de amostras em ±1 ou 0/1 |

Fórmulas detalhadas e casos de borda estão em `references/metrics.md`.

## Protocolo de captura

1. **Aquecimento** — 2 s com o controle conectado e sem tocar.
2. **Repouso** — 5 s sem tocar; descarte o primeiro segundo.
3. **Círculos** — 3 voltas completas no sentido horário e 3 no anti-horário, ~2 s cada, tentando manter o stick na borda do gate.
4. **Triggers** — 5 pressões lentas completas, ~2 s cada, com 0,5 s parado no repouso e no fundo.
5. **Botões** — 5 pressões por botão, com intervalo.
6. **Repetição** — repita a sessão pelo menos 2 vezes, reconnectando se possível.
7. **Registro** — salve raw + timestamp + metadata; não salve apenas o resultado calculado.

Use o mesmo protocolo para comparar dispositivos. Sem protocolo, a comparação não é válida.

## Critérios de aceite iniciais

Valores de partida, não universais. Ajuste por classe e valide com uma amostra maior.

| Métrica | Alvo inicial | Observação |
| --- | --- | --- |
| Drift em repouso | < 0,02 normalizado | Depende do tempo e da temperatura |
| Ruído RMS | < 0,005 normalizado | Meça antes de filtrar |
| Deadzone recomendada | ≥ raio de ruído | Evite esconder ruído com valor arbitrário |
| Circularidade | > 0,90 | Gates quadrados/octogonais falham |
| Linearidade do trigger | R² > 0,98 | Inclua histerese no relatório |
| Histerese do trigger | < 0,03 | Pode ser maior em triggers com mola |
| Taxa efetiva | ±10% da nominal | Bluetooth pode variar |

Registre também o pior caso, não só a média.

## Pitfalls

- **Deadzone de firmware** já aplicada: medir antes de adicionar outra.
- **Gate não circular**: circularidade baixa pode ser mecânica, não defeito.
- **Trigger com repouso > 0**: normalizar pelo repouso medido, não por zero.
- **Filtros do SO/Steam Input**: podem alterar a resposta; documente a camada.
- **Eixos invertidos**: não confunda inversão de sinal com range negativo.
- **Bluetooth**: latência e jitter maiores; não compare diretamente com USB.
- **Amostra curta**: ruído e drift precisam de janela suficiente.
- **Média simples**: um outlier distorce; use mediana para centro e reporte p95/p99.
- **Circularidade com poucos pontos**: use pelo menos 100 amostras por volta.

## Relatório

```markdown
## Dispositivo
- Nome/VID/PID:
- Backend/SO/conexão:
- Firmware:

## Captura
- Arquivo:
- Taxa efetiva:
- Duração:
- Protocolo:

## Sticks
| Stick | Centro | Drift | Ruído RMS | Range | Circularidade | Deadzone sugerida |
| --- | --- | --- | --- | --- | --- | --- |
| Esquerdo | | | | | | |
| Direito | | | | | | |

## Triggers
| Trigger | Repouso | Fundo | R² | Erro máx. | Histerese |
| --- | --- | --- | --- | --- | --- |
| L2 | | | | | |
| R2 | | | | | |

## Riscos e observações
```

## Checklist

- [ ] A camada e a unidade foram declaradas.
- [ ] O protocolo foi seguido e registrado.
- [ ] O repouso foi medido, não assumido.
- [ ] O relatório inclui pior caso e dispersão.
- [ ] Deadzone de firmware foi considerada.
- [ ] A captura raw foi preservada para replay.
- [ ] Os critérios são adequados à classe do dispositivo.
