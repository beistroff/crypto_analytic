# Releasing

One roadmap step (`docs/IMPLEMENTATION_PLAN.md`, section 0.2) is one branch, one PR and one release tag. A PR that touches DynamoDB or the instance merges only after its manual test cases pass.

## 1. Run `sentinel` on the laptop

Manual test cases run the branch's `sentinel` with keys from aws-vault. In PowerShell from the repo root, put the venv on `PATH` once per terminal (aws-vault starts `sentinel` as a child process, which looks it up there):

```powershell
$env:Path = "$PWD\.venv\Scripts;$env:Path"
aws-vault exec sentinel-deploy -- sentinel market scan --limit 10 --format telegram
```

## 2. Push and open the PR

Fill the body from `.github/pull_request_template.md` (What and why, Changes, Checked, After merge) in a file outside the repo, then:

```bash
gh pr create --base main --head feat/<short-name> --title "feat: <summary>" --body-file <path-to-body.md>
```

Wait for CI to pass and for the manual test cases named in the PR body.

## 3. Merge and tag

Squash-merge on GitHub, then:

```bash
git checkout main
git pull
git tag -a v0.1.N -m "<step in a few words>"
git push origin v0.1.N
```

Bump `__version__` in `sentinel/__init__.py` in the PR so that `sentinel --version` matches the tag.

## 4. Update the instance

Connect with `aws ssm start-session --target <instance-id>`, then `sudo -iu ubuntu`. `~/sentinel/src` is a shallow clone at a tag (`openclaw/bootstrap.sh`), so fetch the new tag and reinstall:

```bash
git -C ~/sentinel/src fetch --depth 1 origin tag v0.1.N
git -C ~/sentinel/src checkout v0.1.N
~/sentinel/venv/bin/pip install --quiet -c ~/sentinel/src/constraints.txt -e ~/sentinel/src[ec2]
git -C ~/sentinel/src describe --tags
```

If the PR changed `openclaw/workspace/` files, copy them into `~/.openclaw/workspace/` and send `/new` in Telegram. Copy only the changed files: `USER.md` and `memory/` stay as they are on the instance.

## 5. Smoke test

```bash
~/sentinel/venv/bin/sentinel health --format telegram
~/sentinel/venv/bin/sentinel snapshot BTC --format telegram
~/sentinel/venv/bin/sentinel market scan --limit 10 --format telegram
```

Then ask one question in Telegram. Finish with the PR's "After merge" steps and its post-merge test cases.
