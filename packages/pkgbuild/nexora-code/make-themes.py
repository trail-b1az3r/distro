#!/usr/bin/env python3
"""The editor's themes, from the distribution's colours (distro.conf's BRAND_*), and the map the built-in
extension uses to give "<Name> Material" Halcyon's colours at run time.

Everything is said in Material 3 colour roles (the roles Halcyon writes to
~/.local/state/quickshell/user/generated/colors.json): MAP says which role each part of the editor takes, and
TOKENS which role each kind of code takes. Here the roles are made from the brand colours; at run time the extension
reads them from Halcyon's file and applies the same MAP.

    make-themes.py OUT_DIR BG SURFACE FG MUTED ACCENT ACCENT2 WARNING DANGER
"""
import colorsys
import json
import sys
from pathlib import Path

# Editor colour -> [role, alpha (0-1, optional)].
MAP = {
    "foreground": ["on_surface"],
    "descriptionForeground": ["on_surface_variant"],
    "disabledForeground": ["outline"],
    "errorForeground": ["error"],
    "focusBorder": ["primary", 0.8],
    "contrastBorder": ["outline_variant", 0.0],
    "selection.background": ["primary", 0.35],
    "icon.foreground": ["on_surface_variant"],
    "widget.shadow": ["shadow", 0.5],
    "scrollbar.shadow": ["shadow", 0.0],
    "scrollbarSlider.background": ["on_surface", 0.12],
    "scrollbarSlider.hoverBackground": ["on_surface", 0.2],
    "scrollbarSlider.activeBackground": ["primary", 0.5],
    "badge.background": ["primary"],
    "badge.foreground": ["on_primary"],
    "button.background": ["primary"],
    "button.foreground": ["on_primary"],
    "button.hoverBackground": ["primary", 0.85],
    "button.secondaryBackground": ["secondary_container"],
    "button.secondaryForeground": ["on_secondary_container"],
    "checkbox.background": ["surface_container_high"],
    "checkbox.border": ["outline"],
    "dropdown.background": ["surface_container_high"],
    "dropdown.border": ["outline_variant"],
    "input.background": ["surface_container_highest"],
    "input.border": ["outline_variant", 0.0],
    "input.foreground": ["on_surface"],
    "input.placeholderForeground": ["on_surface_variant", 0.7],
    "inputOption.activeBackground": ["primary", 0.3],
    "inputOption.activeBorder": ["primary"],
    "progressBar.background": ["primary"],
    "textLink.foreground": ["primary"],
    "textLink.activeForeground": ["primary"],
    "titleBar.activeBackground": ["surface_container_low"],
    "titleBar.activeForeground": ["on_surface"],
    "titleBar.inactiveBackground": ["surface_container_lowest"],
    "titleBar.inactiveForeground": ["on_surface_variant"],
    "titleBar.border": ["outline_variant", 0.0],
    "commandCenter.background": ["surface_container_high"],
    "commandCenter.foreground": ["on_surface"],
    "commandCenter.border": ["outline_variant", 0.0],
    "commandCenter.activeBackground": ["surface_container_highest"],
    "menu.background": ["surface_container"],
    "menu.foreground": ["on_surface"],
    "menu.selectionBackground": ["secondary_container"],
    "menu.selectionForeground": ["on_secondary_container"],
    "menu.separatorBackground": ["outline_variant"],
    "menubar.selectionBackground": ["secondary_container"],
    "activityBar.background": ["surface_container_low"],
    "activityBar.foreground": ["primary"],
    "activityBar.inactiveForeground": ["on_surface_variant"],
    "activityBar.border": ["outline_variant", 0.0],
    "activityBar.activeBorder": ["primary"],
    "activityBar.activeBackground": ["secondary_container", 0.6],
    "activityBarBadge.background": ["tertiary"],
    "activityBarBadge.foreground": ["on_tertiary"],
    "sideBar.background": ["surface_container_low"],
    "sideBar.foreground": ["on_surface"],
    "sideBar.border": ["outline_variant", 0.0],
    "sideBarTitle.foreground": ["on_surface_variant"],
    "sideBarSectionHeader.background": ["surface_container_low"],
    "sideBarSectionHeader.foreground": ["on_surface"],
    "sideBarSectionHeader.border": ["outline_variant", 0.0],
    "list.activeSelectionBackground": ["secondary_container"],
    "list.activeSelectionForeground": ["on_secondary_container"],
    "list.inactiveSelectionBackground": ["secondary_container", 0.6],
    "list.hoverBackground": ["on_surface", 0.08],
    "list.focusOutline": ["primary", 0.0],
    "list.highlightForeground": ["primary"],
    "list.errorForeground": ["error"],
    "list.warningForeground": ["warning"],
    "editorGroupHeader.tabsBackground": ["surface_container_low"],
    "editorGroupHeader.tabsBorder": ["outline_variant", 0.0],
    "editorGroup.border": ["outline_variant", 0.5],
    "tab.activeBackground": ["background"],
    "tab.activeForeground": ["on_surface"],
    "tab.activeBorderTop": ["primary"],
    "tab.inactiveBackground": ["surface_container_low"],
    "tab.inactiveForeground": ["on_surface_variant"],
    "tab.hoverBackground": ["surface_container"],
    "tab.border": ["surface_container_low"],
    "breadcrumb.foreground": ["on_surface_variant"],
    "breadcrumb.focusForeground": ["on_surface"],
    "breadcrumb.background": ["background"],
    "editor.background": ["background"],
    "editor.foreground": ["on_surface"],
    "editorLineNumber.foreground": ["outline"],
    "editorLineNumber.activeForeground": ["primary"],
    "editorCursor.foreground": ["primary"],
    "editor.selectionBackground": ["primary", 0.3],
    "editor.inactiveSelectionBackground": ["primary", 0.15],
    "editor.selectionHighlightBackground": ["tertiary", 0.18],
    "editor.wordHighlightBackground": ["tertiary", 0.15],
    "editor.findMatchBackground": ["tertiary", 0.45],
    "editor.findMatchHighlightBackground": ["tertiary", 0.22],
    "editor.lineHighlightBackground": ["on_surface", 0.05],
    "editor.lineHighlightBorder": ["on_surface", 0.0],
    "editorIndentGuide.background1": ["outline_variant", 0.6],
    "editorIndentGuide.activeBackground1": ["outline"],
    "editorWhitespace.foreground": ["outline_variant"],
    "editorBracketMatch.background": ["primary", 0.2],
    "editorBracketMatch.border": ["primary", 0.6],
    "editorWidget.background": ["surface_container_high"],
    "editorWidget.border": ["outline_variant"],
    "editorSuggestWidget.background": ["surface_container_high"],
    "editorSuggestWidget.selectedBackground": ["secondary_container"],
    "editorSuggestWidget.highlightForeground": ["primary"],
    "editorHoverWidget.background": ["surface_container_high"],
    "editorHoverWidget.border": ["outline_variant"],
    "editorError.foreground": ["error"],
    "editorWarning.foreground": ["warning"],
    "editorInfo.foreground": ["primary"],
    "editorGutter.addedBackground": ["tertiary"],
    "editorGutter.modifiedBackground": ["primary"],
    "editorGutter.deletedBackground": ["error"],
    "minimap.background": ["background"],
    "minimapSlider.background": ["on_surface", 0.08],
    "peekView.border": ["primary"],
    "peekViewEditor.background": ["surface_container_lowest"],
    "peekViewResult.background": ["surface_container"],
    "peekViewTitle.background": ["surface_container_high"],
    "panel.background": ["surface_container_low"],
    "panel.border": ["outline_variant", 0.5],
    "panelTitle.activeBorder": ["primary"],
    "panelTitle.activeForeground": ["on_surface"],
    "panelTitle.inactiveForeground": ["on_surface_variant"],
    "terminal.background": ["surface_container_low"],
    "terminal.foreground": ["on_surface"],
    "terminalCursor.foreground": ["primary"],
    "terminal.ansiBlack": ["surface_container_highest"],
    "terminal.ansiRed": ["error"],
    "terminal.ansiGreen": ["tertiary"],
    "terminal.ansiYellow": ["warning"],
    "terminal.ansiBlue": ["primary"],
    "terminal.ansiMagenta": ["on_primary_container"],
    "terminal.ansiCyan": ["tertiary"],
    "terminal.ansiWhite": ["on_surface"],
    "terminal.ansiBrightBlack": ["outline"],
    "terminal.ansiBrightRed": ["error"],
    "terminal.ansiBrightGreen": ["tertiary"],
    "terminal.ansiBrightYellow": ["warning"],
    "terminal.ansiBrightBlue": ["primary"],
    "terminal.ansiBrightMagenta": ["on_primary_container"],
    "terminal.ansiBrightCyan": ["tertiary"],
    "terminal.ansiBrightWhite": ["on_surface"],
    "statusBar.background": ["surface_container_low"],
    "statusBar.foreground": ["on_surface_variant"],
    "statusBar.border": ["outline_variant", 0.0],
    "statusBar.noFolderBackground": ["surface_container_low"],
    "statusBar.debuggingBackground": ["tertiary"],
    "statusBar.debuggingForeground": ["on_tertiary"],
    "statusBarItem.remoteBackground": ["primary"],
    "statusBarItem.remoteForeground": ["on_primary"],
    "statusBarItem.hoverBackground": ["on_surface", 0.08],
    "notifications.background": ["surface_container_high"],
    "notifications.foreground": ["on_surface"],
    "notificationCenterHeader.background": ["surface_container_highest"],
    "quickInput.background": ["surface_container_high"],
    "quickInput.foreground": ["on_surface"],
    "quickInputList.focusBackground": ["secondary_container"],
    "quickInputList.focusForeground": ["on_secondary_container"],
    "pickerGroup.foreground": ["primary"],
    "pickerGroup.border": ["outline_variant"],
    "keybindingLabel.background": ["surface_container_highest"],
    "keybindingLabel.foreground": ["on_surface"],
    "keybindingLabel.border": ["outline_variant"],
    "keybindingLabel.bottomBorder": ["outline"],
    "welcomePage.tileBackground": ["surface_container"],
    "welcomePage.tileHoverBackground": ["surface_container_high"],
    "gitDecoration.addedResourceForeground": ["tertiary"],
    "gitDecoration.modifiedResourceForeground": ["primary"],
    "gitDecoration.deletedResourceForeground": ["error"],
    "gitDecoration.untrackedResourceForeground": ["tertiary"],
    "gitDecoration.ignoredResourceForeground": ["outline"],
}

# Kinds of code -> [role, font style].
TOKENS = [
    (["comment", "punctuation.definition.comment"], "outline", "italic"),
    (["keyword", "storage.type", "storage.modifier", "keyword.control"], "primary", ""),
    (["string", "string.quoted", "markup.inline.raw"], "tertiary", ""),
    (["constant.numeric", "constant.language", "constant.character", "support.constant"], "warning", ""),
    (["entity.name.function", "support.function", "meta.function-call"], "on_primary_container", ""),
    (["entity.name.type", "entity.name.class", "support.type", "support.class", "entity.other.inherited-class"],
     "on_tertiary_container", ""),
    (["variable", "variable.other", "meta.definition.variable"], "on_surface", ""),
    (["variable.parameter"], "on_surface_variant", "italic"),
    (["entity.name.tag", "meta.tag"], "primary", ""),
    (["entity.other.attribute-name"], "tertiary", "italic"),
    (["keyword.operator", "punctuation"], "on_surface_variant", ""),
    (["invalid", "invalid.illegal"], "error", ""),
    (["markup.heading", "entity.name.section"], "primary", "bold"),
    (["markup.bold"], "on_surface", "bold"),
    (["markup.italic"], "on_surface", "italic"),
    (["markup.underline.link", "string.other.link"], "primary", "underline"),
]


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hexc(c):
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02X}" for v in c)


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return hexc(tuple(x + (y - x) * t for x, y in zip(a, b)))


def tone(h, lightness):
    r, g, b = rgb(h)
    hue, _, sat = colorsys.rgb_to_hls(r, g, b)
    return hexc(colorsys.hls_to_rgb(hue, lightness, sat))


def roles(bg, surface, fg, muted, accent, accent2, warning, danger, dark=True):
    """Material roles made from the brand colours."""
    if dark:
        return {
            "background": bg, "surface": bg,
            "surface_container_lowest": mix(bg, "#000000", 0.25),
            "surface_container_low": mix(bg, surface, 0.5),
            "surface_container": surface,
            "surface_container_high": mix(surface, fg, 0.06),
            "surface_container_highest": mix(surface, fg, 0.12),
            "on_surface": fg, "on_surface_variant": muted,
            "outline": mix(muted, bg, 0.3), "outline_variant": mix(muted, bg, 0.65),
            "primary": accent, "on_primary": tone(accent, 0.12),
            "primary_container": tone(accent, 0.28), "on_primary_container": tone(accent, 0.85),
            "secondary_container": mix(surface, accent, 0.25), "on_secondary_container": fg,
            "tertiary": accent2, "on_tertiary": tone(accent2, 0.1),
            "on_tertiary_container": tone(accent2, 0.82),
            "error": danger, "warning": warning, "shadow": "#000000",
        }
    paper = "#FBFAFF"
    ink = tone(bg, 0.12)
    return {
        "background": paper, "surface": paper,
        "surface_container_lowest": "#FFFFFF",
        "surface_container_low": mix(paper, accent, 0.03),
        "surface_container": mix(paper, accent, 0.06),
        "surface_container_high": mix(paper, accent, 0.09),
        "surface_container_highest": mix(paper, accent, 0.13),
        "on_surface": ink, "on_surface_variant": mix(ink, paper, 0.3),
        "outline": mix(ink, paper, 0.5), "outline_variant": mix(ink, paper, 0.8),
        "primary": tone(accent, 0.45), "on_primary": "#FFFFFF",
        "primary_container": tone(accent, 0.9), "on_primary_container": tone(accent, 0.3),
        "secondary_container": mix(paper, accent, 0.18), "on_secondary_container": ink,
        "tertiary": tone(accent2, 0.32), "on_tertiary": "#FFFFFF",
        "on_tertiary_container": tone(accent2, 0.25),
        "error": tone(danger, 0.42), "warning": tone(warning, 0.36), "shadow": "#000000",
    }


def color(r, entry):
    value = r.get(entry[0], r["on_surface"])
    if len(entry) > 1:
        return value + f"{round(entry[1] * 255):02X}"
    return value


def theme(name, r, dark):
    return {
        "name": name,
        "type": "dark" if dark else "light",
        "semanticHighlighting": True,
        "colors": {key: color(r, entry) for key, entry in MAP.items()},
        "tokenColors": [
            {"scope": scopes, "settings": {"foreground": r[role], **({"fontStyle": style} if style else {})}}
            for scopes, role, style in TOKENS
        ],
    }


def main(argv):
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    brand = argv[1:9]
    dark, light = roles(*brand, dark=True), roles(*brand, dark=False)
    (out / "dark.json").write_text(json.dumps(theme("Dark", dark, True), indent=1))
    (out / "light.json").write_text(json.dumps(theme("Light", light, False), indent=1))
    # Material starts as Dark; the extension gives it Halcyon's colours.
    (out / "material-dark.json").write_text(json.dumps(theme("Material", dark, True), indent=1))
    (out / "map.json").write_text(json.dumps({"colors": MAP, "tokens": [[s, r, st] for s, r, st in TOKENS],
                                               "fallback": dark}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
