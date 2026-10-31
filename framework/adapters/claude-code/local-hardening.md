# Claude Code on a developer machine

This guide hardens a developer machine that runs Claude Code: the CLI and the editor extension (D95).
P9 says to pin the harness and its extensions. This guide gives the settings for the pin, and the
limits on the agent. The last section is a runbook for a compromised tool.

Facts marked `[TO CONFIRM]` are not in the current official docs. Each one names the URL that was
checked. Test each one on your machine before you trust it.

## What this guide protects against

| Threat | Control in this guide | Stops it? |
| --- | --- | --- |
| A bad release installs with no review (dossier F20) | Auto-update off, an exact version pin, a reviewed pin move | Yes, until a human approves the bad version |
| An agent reads a credential file because of an injected instruction | Deny rules and the sandbox | Partly. See "What deny rules do not stop". |
| A malicious build of the harness or the extension | Long-lived keys off the host, a container or a VM for untrusted work, the runbook | No. A malicious build ignores its own settings. |

The 2026-10-29 incident was a malicious build of the extension (dossier F20, F23). Deny rules and
the sandbox limit the agent. They are not a defense against the tool itself. The pin, and keys that
are not on the host, are the controls for a bad build.

## 1. Turn off auto-update and pin the version

### The CLI

A native install and an npm install update themselves in the background. Homebrew, WinGet, apt,
dnf, and apk installs do not (dossier F24). Do not set `CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE`,
because it turns on updates for Homebrew and WinGet.

1. Add this block to `~/.claude/settings.json`:

   ```json
   {
     "env": { "DISABLE_AUTOUPDATER": "1" }
   }
   ```

2. Run `claude doctor`.
3. Make sure that the `Auto-updates` line shows `disabled (set by env: DISABLE_AUTOUPDATER)`.
4. Run `claude --version`.
5. Record the version.

`DISABLE_AUTOUPDATER` stops only the background check. `claude update` and `claude install` still
work. To block them too, set `DISABLE_UPDATES` to `"1"`. It also blocks `claude install`, so remove
it before a pin move and set it again after (section 5).

Do not use these keys as a pin:

| Key | What it does | Why it is not a pin |
| --- | --- | --- |
| `autoUpdatesChannel: "stable"` | Follows a channel that is about one week old | A delay, not a pin. The owner chose no waiting period (D91). |
| `minimumVersion` | Sets a floor for updates | A floor, not an exact version |
| `requiredMinimumVersion`, `requiredMaximumVersion` | Refuse to start outside a range | Managed settings only |

The settings reference lists no `autoUpdates` key. Use the `env` block. Checked:
https://code.claude.com/docs/en/settings-reference.md

### The editor extension

The extension bundles its own copy of the CLI. Its version is the version of that CLI. The
extension ID is `anthropic.claude-code`.

VS Code:

1. Open the Extensions view.
2. Right-click Claude Code.
3. Clear **Auto Update**.
4. To pin a version, right-click Claude Code again.
5. Select **Install Another Version**, and select the pinned version.
6. Set `"extensions.autoCheckUpdates": false` in the user settings of the editor.

From a shell, `code --install-extension anthropic.claude-code@<version>` installs an exact version.
`code --list-extensions --show-versions` shows the installed version.

Facts to test:

- `[TO CONFIRM]` that `"extensions.autoUpdate": false` turns off auto-update for all extensions.
  The docs name the setting but not its values. Checked:
  https://code.visualstudio.com/docs/configure/extensions/extension-marketplace
- `[TO CONFIRM]` that the editor, not the bundled CLI, updates the extension. Checked:
  https://code.claude.com/docs/en/vs-code.md
- `[TO CONFIRM]` that the bundled CLI does not update itself, and that `DISABLE_AUTOUPDATER` has no
  effect on the extension. Checked: https://code.claude.com/docs/en/vs-code.md

Cursor installs third-party extensions from the Open VSX registry. The 2026-10-29 build came
through the marketplace of Cursor (dossier F20).

- `[TO CONFIRM]` that Cursor has the same **Auto Update** item and **Install Another Version** item
  as VS Code. The docs do not say. Checked: https://cursor.com/docs/configuration/extensions
- `[TO CONFIRM]` that the `cursor` CLI accepts `--install-extension anthropic.claude-code@<version>`.
  Checked: https://cursor.com/docs/configuration/extensions
- The Cursor docs name a team setting that defers updates by a minimum number of hours. It is a
  delay, not a pin, so this guide does not use it.

### Stop the automatic reinstall of the extension

If you run `claude` in a VS Code terminal, the CLI installs the extension. That install can bring a
version that is not your pin. Turn it off in `~/.claude.json`, not in `settings.json`:

```json
{ "autoInstallIdeExtension": false }
```

To skip it for one session, set `CLAUDE_CODE_IDE_SKIP_AUTO_INSTALL=1`.

## 2. Deny rules for credential paths

A `Read` deny rule stops the file tools of the agent from reading a path. Put the rules in
`~/.claude/settings.json`, so they apply in each project. Use `~/` for a path from the home folder.
A single leading `/` is not an absolute path in a rule. A bare file name such as `.env` matches at
any depth under the current folder.

```json
{
  "permissions": {
    "deny": [
      "Read(~/.ssh/**)",
      "Edit(~/.ssh/**)",
      "Read(~/.aws/**)",
      "Read(~/.config/gcloud/**)",
      "Read(~/.azure/**)",
      "Read(~/.kube/**)",
      "Read(~/.docker/config.json)",
      "Read(~/.netrc)",
      "Read(~/.git-credentials)",
      "Read(~/.config/gh/**)",
      "Read(~/.npmrc)",
      "Read(~/.pypirc)",
      "Read(~/.gnupg/**)",
      "Read(.env)",
      "Read(.env.*)"
    ]
  }
}
```

The `Edit(~/.ssh/**)` rule stops the file tools and redirects from a change to `authorized_keys`. Add other
credential paths that your tools use. Deny rules from each settings file apply. A deny rule wins
over an allow rule from any file (dossier F24).

To make the file tools refuse reads outside the working folders, also set
`"permissions": { "blockReadsOutsideWorkingDirectories": true }`. It needs version 2.1.257 or later.
It does not block a shell command in the same way, except in the sandbox.

### What deny rules do not stop

| Gap | Why |
| --- | --- |
| A malicious build of the harness | The tool applies the rules. A bad build ignores its own settings. |
| A script that opens a file itself, for example a Python or Node script | The rules apply to the file tools, to file commands such as `cat`, and to redirects. They do not apply to a subprocess. |
| A command that reads a file with no file name, for example `grep -r` in the parent folder | The command does not name the path. |
| A credential in an environment variable | A path rule does not cover a variable. |
| A hook, a local MCP server, or a status line command | These run with full access. |

The sandbox in section 3 closes the subprocess gap for shell commands. Nothing in the settings closes
the gap for a malicious build.

## 3. The sandbox

The sandbox runs each `Bash` command, and the processes that it starts, under OS controls. macOS
uses Seatbelt. Linux and WSL2 use bubblewrap, and need `bubblewrap` and `socat`. Native Windows has
no sandbox. Use WSL2 for a sandbox on Windows (dossier F24).

| Area | Default in the sandbox |
| --- | --- |
| Write | Only the working folder, a temp folder, and added folders |
| Read | Most of the machine, also `~/.ssh` and `~/.aws/credentials` |
| Network | Through a local proxy. The allowed list starts empty. The permission mode decides what happens to other hosts. |
| Environment | The variables of the harness, also secrets |

With the sandbox on, the paths of your `Read` deny rules also apply to sandboxed commands. Thus the
deny rules in section 2 cover a script in a sandboxed command too.

To turn it on, run `/sandbox` in a session, or add this block to `~/.claude/settings.json`:

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "credentials": {
      "envVars": [{ "name": "GITHUB_TOKEN", "mode": "deny" }]
    }
  }
}
```

| Key | Effect |
| --- | --- |
| `enabled` | Sandboxes each `Bash` command. The default is `false`. |
| `failIfUnavailable` | The CLI does not start if the sandbox cannot start. Without it, commands run with no sandbox. |
| `allowUnsandboxedCommands: false` | Strict mode. The agent cannot retry a blocked command outside the sandbox. |
| `credentials.envVars` | Removes a variable from each sandboxed command. List each secret variable that you keep in the shell. |

Limits of the sandbox:

- It does not apply to the file tools (Read, Edit, Write) or to the web tools. The permission rules
  control those.
- A command that matches `excludedCommands` runs with full access.
- A command that you type at the `!` prompt usually runs with no sandbox.
- `docker` does not work in the sandbox. On macOS, `git` over SSH fails in the sandbox.
- On Linux and WSL2, the `Read(~/.ssh/**)` rule hides the key files from sandboxed commands. Thus
  `git` over SSH can fail there too.
- A malicious build of the harness is not under its own sandbox.

## 4. Keep long-lived keys off the host

A backdoor can read each file and each variable that your user can read. The 2026-10-29 build sent
the names of credential variables to the attacker (dossier F20). Keep fewer secrets on the host.

| Credential | Do this | Not this |
| --- | --- | --- |
| SSH | A hardware key (OpenSSH type `ed25519-sk` or `ecdsa-sk`), or an SSH agent that holds the key | A key file with no passphrase in `~/.ssh` |
| Cloud | Short-lived tokens from a single sign-on login | Access keys in `~/.aws/credentials` or in a variable |
| Git host | A credential helper that uses the OS keychain, and a token with an expiry date and a small scope | A token in `~/.git-credentials` or in `.env` |
| Package registry | A token for each project with a small scope and an expiry date | One token with publish access in `~/.npmrc` |
| Harness | The login of the harness, or a key with a spend limit | A key in a shell startup file |

For untrusted work, run the agent in a dev container or a VM with no host credentials. Untrusted work
is, for example, a repo from an unknown author, or an instruction file that you did not review
(dossier F19). Mount only the project folder. Give the container its own short-lived tokens.

## 5. Move a pin in a reviewed way

A pin moves only after a review (P9, D91). These steps are for macOS and Linux. The release files
are at `https://downloads.claude.ai/claude-code-releases/<version>/`. Signed manifests exist from
version 2.1.89.

Do not use `install.sh` for a pin move. It always downloads the newest release first and runs it.
Thus an unreviewed build runs before the pinned one.

1. Read the release notes between the old and the new version.
2. If a security notice for the new version is open, do not move the pin.
3. Run `curl -fsSL https://downloads.claude.ai/keys/claude-code.asc | gpg --import`.
4. Run `gpg --fingerprint security@anthropic.com`.
5. Make sure that the fingerprint is `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`.
6. Download `manifest.json` and `manifest.json.sig` of the new version.
7. Run `gpg --verify manifest.json.sig manifest.json`.
8. Make sure that the result shows `Good signature`.
9. Download the binary of the new version for your platform.
10. Compare its SHA-256 with `platforms.<platform>.checksum` in `manifest.json`.
11. If `DISABLE_UPDATES` is set, remove it.
12. Run `./claude install <version>` from the checked binary.
13. Set `DISABLE_UPDATES` again, if you use it.
14. For the extension, install the exact version (section 1).
15. Record the new versions in a file that the team repo tracks.
16. Open a PR for that change. A human reviews it.

Facts to test:

- `[TO CONFIRM]` that the binary is at `<version>/<platform>/claude` in the release folder. The docs
  give the manifest path only. Checked: https://code.claude.com/docs/en/setup.md
- `[TO CONFIRM]` that `claude install <version>` installs that exact version. Checked:
  https://code.claude.com/docs/en/setup.md

For a team repo, `requiredMinimumVersion` and `requiredMaximumVersion` in managed settings can hold
each machine to one version. This needs managed settings.

## 6. Runbook: a compromised tool

Use this runbook when a notice says that a version of a tool that you run is bad. It has manual
checks only. The indicators come from the notice of the marketplace owner and one news report
(dossier F20, F23). For a different incident, use the indicators of its notice.

An uninstall may not remove the backdoor (dossier F23). Do each step.

### Find out if you are affected

1. Read the bad versions, the platforms, and the time window in the notice.
2. For 2026-10-29, the bad versions are 2.1.312 and 2.1.313, for macOS and Windows.
3. The window was 2:27 to 13:35 PT on 2026-10-29, in the marketplace of Cursor.
4. Find out if the editor installed or updated the extension in that window.
5. Do the checks in "Check for the SSH key".
6. If you installed a bad version in the window, do all the steps below.
7. If you find the `svc-telemetry` key, do all the steps below.

### Contain

1. If you can, disconnect the machine from the network.
2. Use a different, trusted machine for each login and each credential change.

### Check for the SSH key

1. Open `~/.ssh/authorized_keys`.
2. Look for a key with the comment `svc-telemetry`.
3. On Windows, also open `C:\ProgramData\ssh\administrators_authorized_keys`.
4. Look for each other key that you do not know.
5. Write down each bad key.
6. Remove each bad key.

### Check for persistence

macOS:

1. List the files in `~/Library/LaunchAgents`, `/Library/LaunchAgents`, and `/Library/LaunchDaemons`.
2. Look for `com.apple.sysmond.plist` in `~/Library/LaunchAgents`.
3. Look for each other file that you did not install.
4. Run `launchctl list`.
5. Look for the same labels.

Linux:

1. Run `crontab -l`.
2. Look for an `@reboot` line that runs `~/.config/.smt`.
3. Run `systemctl --user list-unit-files`.
4. Run `systemctl --user list-timers`.
5. Look for each unit or timer that you did not install.

Windows:

1. Run `schtasks /query /fo LIST /v`.
2. Look for a task named `SysMon`.
3. Look in the Startup folder for `sysmon.cmd`.

Each system:

1. Look for the files `~/.config/.smt` and `~/.config/.smtk`.
2. On Windows, look for `%USERPROFILE%\.config\smt.cmd` and `%USERPROFILE%\.config\smtk`.
3. Look in the temp folder for files with names that start with `.stk_`.

### Check for a reverse tunnel

1. List the running `ssh` and `autossh` processes.
2. Look for a process with `-R` in its arguments, for example `ssh -N -R '*:0:localhost:22'`.
3. Look for a connection to `134[.]209[.]82[.]225` on port 22 or 8099.
4. Write down each bad process. Do not stop it yet.

The 2026-10-29 scripts start the tunnel again about every 60 seconds. Thus you remove the
persistence first, and then stop the tunnel.

### Check the SSH service

1. If you did not turn on Remote Login (macOS) or the OpenSSH server (Windows), turn it off.
2. Read the SSH server logs for a login from localhost with the `svc-telemetry` key.
3. If you find such a login, rebuild the machine.

### Remove the bad version

1. Remove each persistence file and each scheduled task that you found.
2. Stop each bad tunnel process.
3. Uninstall the bad version of the extension.
4. Install a known good version.
5. Pin the version (section 1).
6. If the notice gives a cleanup script, read it before you run it.
7. If you are not sure that the machine is clean, rebuild it.

`[TO CONFIRM]` the commands to stop a loaded job on macOS, for example
`launchctl bootout gui/$(id -u)/<label>`. The launchd guide does not give them. Checked:
https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html

### Rotate the credentials

Do these steps from a trusted machine. Rotate each credential that the machine could reach, also
if you found no indicator.

1. Remove the SSH public keys of the machine from each server and each git host.
2. Make new SSH keys.
3. Revoke the cloud access keys and sessions.
4. Revoke the git host tokens.
5. Revoke the OAuth apps that the machine used.
6. Revoke the package registry tokens.
7. Revoke the keys and the login of the harness.
8. Make a new CI token with `claude setup-token`.
9. Revoke each other secret that was in a file or a variable on the machine.
10. Read the logs of each service for use of the old credentials.
