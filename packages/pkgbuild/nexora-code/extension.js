// The distribution's built-in editor extension: gives the "<Name> Material" theme Halcyon's current colours
// (~/.local/state/quickshell/user/generated/colors.json: a Halcyon theme's, or the wallpaper's) and follows them as
// they change. Only that theme is touched: the colours go into workbench.colorCustomizations and
// editor.tokenColorCustomizations under "[<Name> Material]", so every other theme stays as it is.
"use strict";

const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");

const MAP = JSON.parse(fs.readFileSync(path.join(__dirname, "themes", "map.json"), "utf8"));

function colorsFile() {
    const state = process.env.XDG_STATE_HOME || path.join(os.homedir(), ".local", "state");
    return path.join(state, "quickshell", "user", "generated", "colors.json");
}

function withAlpha(hex, alpha) {
    return alpha === undefined ? hex : hex + Math.round(alpha * 255).toString(16).padStart(2, "0").toUpperCase();
}

function readRoles() {
    try {
        const roles = JSON.parse(fs.readFileSync(colorsFile(), "utf8"));
        // Halcyon has no warning role: the error colour's warmer neighbour, from the fallback.
        return Object.assign({}, MAP.fallback, roles);
    } catch (e) {
        return null;
    }
}

async function apply(themeName) {
    const settings = vscode.workspace.getConfiguration();
    const key = `[${themeName}]`;
    const roles = settings.get(`${themeId()}.followHalcyon`, true) ? readRoles() : null;

    const colors = Object.assign({}, settings.inspect("workbench.colorCustomizations").globalValue || {});
    const tokens = Object.assign({}, settings.inspect("editor.tokenColorCustomizations").globalValue || {});
    if (!roles) {
        if (!(key in colors) && !(key in tokens)) return;
        delete colors[key];
        delete tokens[key];
    } else {
        const ui = {};
        for (const [name, entry] of Object.entries(MAP.colors)) {
            ui[name] = withAlpha(roles[entry[0]] || roles.on_surface, entry[1]);
        }
        colors[key] = ui;
        tokens[key] = {
            textMateRules: MAP.tokens.map(([scope, role, style]) => ({
                scope,
                settings: Object.assign({ foreground: roles[role] || roles.on_surface }, style ? { fontStyle: style } : {}),
            })),
        };
        if (JSON.stringify(colors[key]) === JSON.stringify((settings.inspect("workbench.colorCustomizations").globalValue || {})[key]))
            return;
    }
    await settings.update("workbench.colorCustomizations", colors, vscode.ConfigurationTarget.Global);
    await settings.update("editor.tokenColorCustomizations", tokens, vscode.ConfigurationTarget.Global);
}

let extensionId = "";
function themeId() {
    return extensionId.split(".")[0];
}

function activate(context) {
    extensionId = context.extension.id;
    const name = context.extension.packageJSON.displayName + " Material";
    let timer = null;
    const later = () => {
        clearTimeout(timer);
        timer = setTimeout(() => apply(name).catch(() => {}), 400);
    };
    later();

    // Halcyon rewrites the file when the theme or the wallpaper changes: watch its folder (the file is replaced).
    const dir = path.dirname(colorsFile());
    try {
        fs.mkdirSync(dir, { recursive: true });
        const watcher = fs.watch(dir, (event, file) => {
            if (!file || file === "colors.json") later();
        });
        context.subscriptions.push({ dispose: () => watcher.close() });
    } catch (e) {
        // No Halcyon here: the theme keeps the distribution's colours.
    }
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration(`${themeId()}.followHalcyon`)) later();
    }));
}

function deactivate() {}

module.exports = { activate, deactivate };
