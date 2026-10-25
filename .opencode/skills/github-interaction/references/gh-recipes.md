# Receitas `gh` / `git`

## Diagnóstico

```bash
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef,viewerPermission
git status --short --branch
git remote -v
git log --oneline -5
```

## Issues

```bash
gh issue list --state open --limit 20
gh issue list --search "is:open label:bug" --limit 20
gh issue view 42 --comments
gh issue create --title "fix: ..." --body-file issue.md --label "bug"
gh issue comment 42 --body "Reproduzido em ..."
gh issue close 42 --comment "Corrigido em #43"
```

## Branches e commits

```bash
git fetch origin
git switch main
git pull --ff-only
git switch -c feat/calibration-wizard
git add -p
git diff --cached
git commit -m "feat(calibration): adiciona wizard inicial"
git push -u origin HEAD
```

## Pull requests

```bash
gh pr create --draft --title "feat(calibration): wizard inicial" --body-file pr.md
gh pr list --state open --limit 20
gh pr view 43
gh pr view 43 --json number,title,state,isDraft,mergeable,reviewDecision,statusCheckRollup,url
gh pr diff 43
gh pr ready 43
gh pr checks 43 --watch
gh pr review 43 --comment --body-file review.md
gh pr review 43 --request-changes --body-file review.md
gh pr review 43 --approve
gh pr merge 43 --squash --delete-branch
```

## Checks e Actions

```bash
gh run list --limit 10
gh run view <run-id>
gh run view <run-id> --log-failed
gh run watch <run-id>
gh workflow list
gh workflow run <workflow>
```

Não reexecute um workflow sem identificar a causa da falha.

## Releases

```bash
gh release list
gh release view v0.1.0
gh release create v0.1.0 --draft --generate-notes --title "v0.1.0"
gh release edit v0.1.0 --draft=false
gh release delete v0.1.0
```

## JSON e jq

```bash
# Estado resumido do PR
gh pr view 43 --json state,isDraft,mergeable,reviewDecision,statusCheckRollup

# Checks falhando
gh pr checks 43 --json name,state,link --jq '.[] | select(.state != "SUCCESS")'

# Issues com label
gh issue list --json number,title,labels --jq '.[] | select(any(.labels[]; .name == "bug"))'

# Últimas runs
gh run list --json databaseId,status,conclusion,workflowName --limit 10
```

## Troubleshooting

```bash
# Qual é o remoto?
git remote -v

# Qual é a branch base?
gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'

# O PR tem conflito?
gh pr view 43 --json mergeable,mergeStateStatus

# O check falhou por quê?
gh run view <run-id> --log-failed

# A branch está atualizada?
git fetch origin
git log --oneline HEAD..origin/main
```

## Regras rápidas

- Leia antes de escrever.
- Não use `--force` em branch compartilhada.
- Não use `--admin` para bypassar proteção.
- Não faça merge com checks vermelhos.
- Não imprima tokens.
- Confirme exclusões e fechamentos.
- Registre URL/SHA como evidência.
