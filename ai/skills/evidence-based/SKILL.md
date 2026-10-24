---
name: evidence-based
description: "Exige que afirmações técnicas sejam sustentadas por evidência verificável, separando fato, inferência, suposição e recomendação. Use ao investigar, revisar, depurar, decidir arquitetura ou responder sobre código, hardware ou comportamento de agentes."
metadata:
  owner: shared
  version: "1.0"
---

# Evidence-Based

## Quando usar

Use esta skill quando a resposta envolver:

- comportamento de código, teste ou configuração;
- diagnóstico de bug ou falha intermitente;
- decisão de arquitetura ou de dependência;
- medição, protocolo ou compatibilidade de hardware;
- avaliação de prompt, skill ou fluxo;
- qualquer afirmação que o usuário possa verificar.

Não use para transformar opinião estética em fato. Preferência continua sendo preferência.

## Princípio

Nenhuma afirmação técnica deve ser apresentada como fato sem evidência verificável. Quando a evidência não existir, declare a lacuna e proponha como verificá-la.

## Categorias de afirmação

| Categoria | Definição | Como apresentar |
| --- | --- | --- |
| Fato | Observado diretamente ou demonstrado | "O teste X passou; saída Y." |
| Inferência | Conclusão derivada de fatos, sujeita a erro | "Isso sugere que...; a inferência depende de..." |
| Suposição | Adotada sem verificação | "Estou assumindo que...; se for falso, o resultado muda." |
| Recomendação | Ação proposta, não um fato | "Recomendo...; o critério de sucesso é..." |
| Desconhecido | Não verificado | "Não verifiquei; para confirmar, rode..." |

Nunca misture as categorias em uma frase que pareça fato.

## Hierarquia de evidência

1. **Reprodução local** — teste, comando, execução ou captura que você produziu.
2. **Artefato primário** — código-fonte, diff, relatório de teste, captura de hardware, datasheet.
3. **Documentação oficial da versão** — doc do projeto, API reference, changelog.
4. **Fonte secundária confiável** — artigo técnico, issue, discussão, com data e contexto.
5. **Inferência** — raciocínio a partir das anteriores.
6. **Suposição** — menor nível; deve ser declarada.

Uma fonte secundária não vence um teste reproduzível. Uma documentação desatualizada não vence o código da versão instalada.

## Como citar

- **Código:** `path/to/file.py:123` e o trecho relevante.
- **Comando:** comando exato + resultado ou trecho da saída.
- **Teste:** nome do teste + comando + resultado.
- **API externa:** URL + versão/data consultada.
- **Hardware:** dispositivo, backend, captura e unidade.
- **Prompt:** caso de teste, ferramenta/modelo e saída observada.

Se você não consegue citar, provavelmente não verificou.

## Quando falta evidência

Responda com:

1. O que você sabe.
2. O que você **não** verificou.
3. A hipótese mais provável e por quê.
4. O teste ou medição que confirmaria.
5. O impacto de estar errado.

Use confiança explícita:

- **Alta:** reproduzido ou medido.
- **Média:** documentação oficial + inferência consistente.
- **Baixa:** suposição ou fonte secundária isolada.

## Aplicação por domínio

### Code review

- Cite arquivo:linha do diff.
- Verifique o comportamento no código, não apenas no nome da função.
- Rode testes quando a mudança for executável.
- Não afirme que um caminho é inalcançável sem rastrear chamadas.

### Debug

- Reproduza antes de corrigir.
- Isole a variável; compare antes/depois.
- Registre o comando e a saída que confirmam a causa.
- Diferencie "a causa é X" de "X é uma hipótese".

### Arquitetura

- Baseie a decisão em restrições observáveis: dependências, acoplamentos, latência, testabilidade.
- Não use "boas práticas" como evidência.
- Registre o trade-off e o que invalidaria a decisão.

### Hardware

- Meça ranges, repouso, ruído e taxa; não assuma.
- Registre dispositivo, firmware, backend e condição de conexão.
- Use captura/replay para tornar a evidência reproduzível.
- Diferencie datasheet de comportamento observado.

### Prompts e agentes

- Compare versões com os mesmos casos.
- Registre disparo de skill, formato e custo.
- Não conclua que uma instrução funciona porque uma única execução foi boa.

## Contrato de resposta

Quando a distinção importar, use:

```markdown
**Fato:** ...
**Evidência:** ...
**Inferência:** ...
**Suposição:** ...
**Recomendação:** ...
**Confiança:** alta/média/baixa
**Verificação pendente:** ...
```

Nem toda resposta precisa de todos os campos, mas nenhuma deve apagar a diferença entre eles.

## Anti-padrões

- "Provavelmente funciona."
- "A API aceita X" sem documentação ou teste.
- "O range é 0–255" sem medição.
- "Os testes passam" sem tê-los executado.
- Tratar um blog ou uma resposta de IA como evidência primária.
- Esconder incerteza para parecer confiante.
- Viés de confirmação: procurar apenas o que sustenta a hipótese.
- Confundir ausência de evidência com evidência de ausência.

## Checklist

- [ ] Cada afirmação técnica tem evidência ou está marcada como inferência/suposição.
- [ ] A evidência é da versão/ambiente correto.
- [ ] Comandos e arquivos citados são reproduzíveis.
- [ ] A confiança está explícita quando importa.
- [ ] Lacunas têm um próximo teste ou medição.
- [ ] Nenhuma recomendação foi apresentada como fato.
