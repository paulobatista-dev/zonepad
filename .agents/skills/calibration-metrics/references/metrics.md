# Fórmulas e casos de borda

## Centro de repouso

Para cada eixo, use a mediana de `N` amostras em repouso:

```text
c = median(x_1..x_N)
```

A mediana é robusta a outliers de um ou dois samples. Reporte também a média e o desvio para detectar assimetria.

## Drift

```text
drift = max_t ||p(t) - c||
```

Para sticks 2D, use a distância euclidiana. Para triggers, use `|x(t) - c|`.

## Ruído

```text
rms = sqrt(mean_t(||p(t) - c||²))
p2p = max_t(p(t)) - min_t(p(t))
```

Calcule por eixo e em 2D. O RMS 2D não é a soma dos RMS por eixo.

## Range e simetria

```text
span = max - min
simetria = (max - c) / (c - min)
```

Se `c - min` ou `max - c` for zero, marque o eixo como inválido; não divida.

## Deadzone radial

```text
r = hypot(x, y)
se r <= dz: saída = (0, 0)
senão:
  cut:      saída = (x, y)
  rescale:  f = (r - dz) / (1 - dz)
            saída = (x / r * f, y / r * f)
```

- `cut` preserva a resposta original, mas cria descontinuidade.
- `rescale` remove a descontinuidade, mas altera a curva perto do centro.
- O padrão do ZonaPad é `cut`; o perfil deve registrar o modo.
- Deadzone axial é `|x| <= dz` e `|y| <= dz`; não confunda com radial.

## Circularidade

Para uma volta completa, calcule `r(θ)` e:

```text
circularidade = min(r) / max(r)
```

Ideal: 1,0. Reporte também `mean(r)`, `std(r)` e o número de amostras. Um gate quadrado tende a valores menores; isso pode ser mecânico.

## Linearidade do trigger

Ajuste `y = a*x + b` por mínimos quadrados na subida:

```text
R² = 1 - SS_res / SS_tot
erro_max = max|y_i - (a*x_i + b)|
```

Reporte `a`, `b`, `R²`, `erro_max` e a faixa usada. Não ajuste se a trigger tiver zona morta de firmware sem documentar.

## Histerese

Para cada posição `x`, compare a subida e a descida:

```text
histerese = max_x |y_up(x) - y_down(x)|
```

Use interpolação se as amostras não estiverem alinhadas. Reporte a posição do pior caso.

## Jitter e taxa

```text
Δt_i = t_i - t_{i-1}
taxa = 1 / mean(Δt)
jitter = std(Δt)
```

Descarte o primeiro intervalo após a conexão. Em Bluetooth, reporte p95 de `Δt`.

## Saturação

```text
saturação = count(|x| >= 0,98) / N
```

Para triggers, use `x >= 0,98` e `x <= 0,02`.

## Casos de borda

- **Amostras insuficientes**: menos de 100 pontos para circularidade ou 1 s para ruído → resultado inconclusivo.
- **Outliers**: use mediana para centro; para ruído, reporte com e sem o pior 1%.
- **Eixo travado**: range zero ou variância zero → device defeituoso ou parser errado.
- **Valores fora do range**: pode ser erro de normalização ou report mal interpretado; não faça clamp silencioso na captura.
- **Timestamp não monotônico**: descarte a sessão ou reordene com cautela; registre o problema.
- **Repouso tocado**: detecte movimento durante a janela e peça nova captura.
- **Deadzone de firmware**: se a saída fica exatamente zero em uma faixa, meça a largura e registre.
- **Trigger com repouso alto**: normalize por `(x - rest) / (max - rest)`, não por `x / max`.
- **Mudança de backend**: não compare capturas de backends diferentes sem declarar.

## Incerteza

Sempre que possível, reporte intervalo de confiança ou dispersão entre sessões. Uma única captura é uma observação, não uma especificação.
