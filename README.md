# Omarchy extra agents

Add **Grok**, **Hermes**, and **Agy** (Antigravity) to Omarchy Quattro’s agents tray, next to Claude and Codex.

You pick which ones. Each tab only lights up if that CLI is already signed in on the machine.

## Install

```bash
git clone https://github.com/inkwisebot-ux/omarchy-extra-agents.git
cd omarchy-extra-agents
./install.sh
```

Checkboxes for Grok, Hermes, and Agy. Then one password prompt so the icons land next to Claude/Codex and come back after an Omarchy upgrade.

Without the menu:

```bash
./install.sh grok hermes agy
./install.sh --all
```

## Uninstall

```bash
./uninstall.sh
```

## After that

Enabled extras are listed in `~/.config/omarchy/extra-agents/enabled`. Hide a tab in the tray with Omarchy’s usual per-agent setting:

```bash
omarchy bar set omarchy.agents providers '{"hermes":{"enabled":false}}' --json
```

Claude’s chip is shortened to **Claude** so five names still fit the switch row.

This is not an `omarchy plugin add` package. The agents plugin is first-party and cannot be replaced, so extras are collectors plus tray marks, which is how Omarchy already adds new agents.

Marks belong to xAI, Nous Research, and Google, and are used only to identify those products in the tray.
The theme-adapted Grok tray marks are based on the 512 px Android icon published
by [grok.com](https://grok.com/images/android-chrome-512x512.png). See the
[xAI Brand Guidelines](https://x.ai/legal/brand-guidelines) for the trademark terms governing its use.
