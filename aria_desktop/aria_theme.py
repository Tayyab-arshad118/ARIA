"""Centralized ARIA Material 3 tokens and reusable flat components."""
import flet as ft

BG, PANEL, INK = ft.Colors.SURFACE, ft.Colors.INVERSE_SURFACE, ft.Colors.ON_SURFACE
BRAND_BLUE = "#2F6BFF"
MUTED, ACCENT, ERROR = ft.Colors.ON_SURFACE_VARIANT, ft.Colors.PRIMARY, ft.Colors.ERROR
SOFT, BORDER = ft.Colors.SECONDARY_CONTAINER, ft.Colors.OUTLINE_VARIANT


def primary_style():
    return ft.ButtonStyle(bgcolor={ft.ControlState.DEFAULT: BRAND_BLUE, ft.ControlState.DISABLED: SOFT},
        color={ft.ControlState.DEFAULT: "#FFFFFF", ft.ControlState.DISABLED: MUTED}, elevation=0,
        shape=ft.StadiumBorder(), animation_duration=180,
        text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_500))


def app_theme(dark=False):
    bg, panel, border, ink = ("#0E1220", "#171E2D", "#2B3446", "#F3F6FC") if dark else ("#F8FAFF", "#FFFFFF", "#E7ECF5", "#111827")
    muted, soft = ("#AEB9CC", "#252F40") if dark else ("#687386", "#F2F5FB")
    shape = ft.RoundedRectangleBorder(radius=20)
    button = dict(bgcolor=ink, foreground_color=bg, elevation=0, shape=ft.StadiumBorder(),
        animation_duration=180, minimum_size=ft.Size(48, 54),
        text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_500), disabled_bgcolor=soft, disabled_foreground_color=muted)
    return ft.Theme(use_material3=True, font_family="Segoe UI", hint_color="#94A0B3",
        scrollbar_theme=ft.ScrollbarTheme(thumb_visibility=False, track_visibility=False, thickness=0),
        color_scheme=ft.ColorScheme(primary=BRAND_BLUE, on_primary="#FFFFFF", surface=bg,
            on_surface=ink, inverse_surface=panel, on_inverse_surface=ink,
            on_surface_variant=muted, outline_variant=border, secondary_container=soft,
            on_secondary_container=ink, primary_container=soft, on_primary_container=ink,
            error="#F2ABA3" if dark else "#8E2A20"),
        card_theme=ft.CardTheme(color=panel, elevation=0, shape=shape, margin=0),
        filled_button_theme=ft.FilledButtonTheme(**button),
        elevated_button_theme=ft.ElevatedButtonTheme(**button),
        outlined_button_theme=ft.OutlinedButtonTheme(bgcolor=panel, foreground_color=ink,
            border_side=ft.BorderSide(0.5, border), shape=ft.StadiumBorder(), elevation=0,
            minimum_size=ft.Size(44, 44), text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_400)),
        text_button_theme=ft.TextButtonTheme(foreground_color=ink, shape=ft.StadiumBorder(),
            minimum_size=ft.Size(44, 44), text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_400)),
        chip_theme=ft.ChipTheme(bgcolor=panel, selected_color=soft, elevation=0, click_elevation=0,
            border_side=ft.BorderSide(0.5, border), shape=ft.StadiumBorder(),
            label_text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_400)),
        divider_theme=ft.DividerTheme(color=border, thickness=0.5, space=16),
        dialog_theme=ft.DialogTheme(bgcolor=panel, elevation=0, shape=shape))


def card(content, padding=20):
    return ft.Container(content, padding=padding, bgcolor=PANEL, border_radius=20,
        border=ft.border.all(0.5, BORDER))


def clean_field(control):
    control.border = ft.InputBorder.NONE
    control.border_color = ft.Colors.TRANSPARENT
    control.focused_border_color = ft.Colors.TRANSPARENT
    control.filled = False
    control.content_padding = ft.padding.symmetric(vertical=12)
    control.text_size = 15
    control.cursor_color = ACCENT
    if control.label:
        control.hint_text, control.label = control.label, None
    return control


def status_pill(label, connected, dark=False):
    fg, bg = (("#A8DEC0", "#133323") if dark else ("#17653A", "#E8F6EE")) if connected else (
        ("#F0CD83", "#352A14") if dark else ("#8A5A00", "#FFF3DB"))
    return ft.Container(ft.Text(label, size=12, color=fg), bgcolor=bg, border_radius=100,
        padding=ft.padding.symmetric(horizontal=12, vertical=7))
