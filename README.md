# Omarchy extra agents

Optional [Grok](https://x.ai), [Hermes](https://nousresearch.com), and [Antigravity](https://antigravity.google) tabs for Omarchy Quattro’s agents tray, next to Claude and Codex.

This is **not** a shell plugin. `omarchy.agents` is first-party and cannot be shadowed, so extras are drop-in collectors plus tray marks, which is how Omarchy already expects new agents to show up.

## Install

On Omarchy 4 (Quattro):

```bash
git clone https://github.com/inkwisebot-ux/omarchy-extra-agents.git
cd omarchy-extra-agents
./install.sh
```

`install.sh` opens gum checkboxes for **Grok**, **Hermes**, and **Agy**. Pick any combination. Non-interactive:

```bash
./install.sh grok hermes agy
./install.sh --all
```

The installer asks for root once so it can copy the marks into `/usr/share/omarchy/shell/plugins/agents/assets/` (the panel only looks there) and so an upgrade hook can put them back after `pacman -Syu`.

You still need the matching CLI signed in: Grok CLI (`~/.grok/auth.json`), Hermes (`~/.hermes`), Antigravity / `agy` (libsecret `service=gemini username=antigravity`).

## What you get

| Tab | Collector | Mark |
|---|---|---|
| Grok | weekly credit window from Grok CLI billing | official slashed-ring |
| Hermes | remaining Nous prepaid credits | official desktop icon (the girl) |
| Agy | Antigravity Gemini vs Claude/GPT pools | official press-kit A |

Claude’s chip is shortened to **Claude** so five tabs still fit the switch row. Omarchy’s own collector prints “Claude Code”; a small stdout shim on `$OMARCHY_PATH/bin/omarchy-agent-usage-claude` rewrites the name before the JSON is written. The real collector in `/usr/bin` is left alone.

## After an Omarchy upgrade

The `omarchy` package owns `/usr/share/omarchy`, so icons and the Claude shim disappear on upgrade. A pacman hook restores them from `~/.local/lib/omarchy-extra-agents`. There is also a user `post-update` hook as a fallback.

## Settings

Enabled extras live in `~/.config/omarchy/extra-agents/enabled`. Hide a tab without uninstalling:

```bash
omarchy bar set omarchy.agents providers '{
  "claude": { "enabled": true },
  "codex": { "enabled": true },
  "grok": { "enabled": true },
  "hermes": { "enabled": false },
  "antigravity": { "enabled": true }
}' --json
```

## Uninstall

```bash
./uninstall.sh
```

## Upstream

The long-term home for this is a pull request to [basecamp/omarchy](https://github.com/basecamp/omarchy), same shape as the Fireworks collector. This repo is the optional, pick-what-you-use version until that lands.

Marks belong to xAI, Nous Research, and Google. They are used here only to identify those products in the tray.
