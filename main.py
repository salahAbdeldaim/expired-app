import flet as ft
import sqlite3

from datetime import datetime
import os
import logging
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import sys

# Optional Arabic shaping libs
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _HAS_ARABIC_LIBS = True
except Exception:
    _HAS_ARABIC_LIBS = False


def _register_arabic_font():
    """Try to find an Arabic-capable TTF on the system and register it with ReportLab.
    Returns the registered font name or None.
    """
    possible_fonts = [
        # Common Windows fonts
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\times.ttf",
        # Noto (if installed)
        r"C:\Windows\Fonts\NotoNaskhArabic-Regular.ttf",
        r"C:\Windows\Fonts\NotoSansArabic-Regular.ttf",
    ]
    for p in possible_fonts:
        try:
            if os.path.exists(p):
                font_name = "AppFont"
                try:
                    pdfmetrics.registerFont(TTFont(font_name, p))
                    return font_name
                except Exception:
                    continue
        except Exception:
            continue
    # fallback: try to register any .ttf in current assets dir
    try:
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        if os.path.isdir(assets_dir):
            for f in os.listdir(assets_dir):
                if f.lower().endswith('.ttf'):
                    p = os.path.join(assets_dir, f)
                    font_name = "AppFont"
                    try:
                        pdfmetrics.registerFont(TTFont(font_name, p))
                        return font_name
                    except Exception:
                        continue
    except Exception:
        pass
    return None


def _reshape_text_for_pdf(text: str) -> str:
    """Return text reshaped for Arabic/Bidi if libs are available, else return as-is."""
    if not text:
        return text
    if _HAS_ARABIC_LIBS:
        try:
            reshaped = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped)
            return bidi_text
        except Exception:
            return text
    return text


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_NAME = "pharmacy.db"

def get_db_path(page):
    base_dir = os.path.join(os.path.expanduser("~"), ".pharmacy_app")  
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, DB_NAME)


def get_connection(db_path):
    return sqlite3.connect(db_path)

def init_db(db_path):
    print(f"Database path: {db_path}")  # يطبع المسار في الكونسول
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # الجداول زي ما هي
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name_en TEXT NOT NULL UNIQUE,
        name_ar TEXT NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity >= 0),
        price REAL NOT NULL CHECK(price >= 0),
        expiry_month INTEGER NOT NULL CHECK(expiry_month BETWEEN 1 AND 12),
        expiry_year INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (type_id) REFERENCES types(id) ON DELETE CASCADE
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pharmacy_name TEXT NOT NULL,
        phone_number TEXT,
        doctor_name TEXT,
        doctor_phone TEXT,
        theme_mode TEXT CHECK(theme_mode IN ('light', 'dark')) DEFAULT 'light'
    )
    """)

    # Migration: ensure new doctor columns exist for older DBs
    try:
        cursor.execute("PRAGMA table_info(settings)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'doctor_name' not in cols:
            try:
                cursor.execute("ALTER TABLE settings ADD COLUMN doctor_name TEXT")
            except Exception:
                pass
        if 'doctor_phone' not in cols:
            try:
                cursor.execute("ALTER TABLE settings ADD COLUMN doctor_phone TEXT")
            except Exception:
                pass
    except Exception:
        # ignore migration errors
        pass

    # فهارس
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_name ON items(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_type ON items(type_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_expiry ON items(expiry_year, expiry_month)")

    # بيانات أولية
    cursor.execute("SELECT COUNT(*) FROM types")
    if cursor.fetchone()[0] == 0:
        medicine_types = [
            ("Tablet", "أقراص"),
            ("Syrup", "شراب"),
            ("Injection", "حقن"),
            ("Capsule", "كبسولات"),
            ("Ointment", "مرهم"),
            ("Drops", "نقط"),
            ("Spray", "بخاخ"),
            ("Cream ", "كريم"),
        ]
        cursor.executemany("INSERT INTO types (name_en, name_ar) VALUES (?, ?)", medicine_types)

    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO settings (pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode) VALUES (?, ?, ?, ?, ?)",
            ("My Pharmacy", "0100000000", "", "", "light")
        )

    conn.commit()
    conn.close()

def show_error_snackbar(page, message):
    error_color = page.theme.color_scheme.error if page.theme and page.theme.color_scheme else ft.Colors.RED
    on_error_container_color = page.theme.color_scheme.on_error_container if page.theme and page.theme.color_scheme else ft.Colors.WHITE
    snack = ft.SnackBar(
        content=ft.Text(
            message,
            text_align=ft.TextAlign.CENTER,
            color=on_error_container_color,
            size=14,
            weight=ft.FontWeight.W_500,
        ),
        bgcolor=error_color,
        duration=3000,
        padding=10,
    )
    page.snack_bar = snack
    snack.open = True
    if snack not in page.overlay:
        page.overlay.append(snack)
    page.update()

def show_success_snackbar(page, message):
    primary_container_color = page.theme.color_scheme.primary_container if page.theme and page.theme.color_scheme else ft.Colors.GREEN_700
    on_primary_container_color = page.theme.color_scheme.on_primary_container if page.theme and page.theme.color_scheme else ft.Colors.WHITE
    snack = ft.SnackBar(
        content=ft.Text(
            message,
            text_align=ft.TextAlign.CENTER,
            color=on_primary_container_color,
            size=14,
            weight=ft.FontWeight.W_500,
        ),
        bgcolor=primary_container_color,
        duration=3000,
        padding=10,
    )
    page.snack_bar = snack
    snack.open = True
    if snack not in page.overlay:
        page.overlay.append(snack)
    page.update()

def contact_page(page: ft.Page):
    # Fallback colors
    default_primary_color = ft.Colors.BLUE
    default_surface_color = ft.Colors.WHITE
    default_on_surface_color = ft.Colors.BLACK
    default_surface_variant_color = ft.Colors.GREY_200
    default_on_surface_variant_color = ft.Colors.GREY_800
    default_error_color = ft.Colors.RED
    default_primary_container_color = ft.Colors.BLUE_100

    primary_color = page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else default_primary_color
    surface_color = page.theme.color_scheme.surface if page.theme and page.theme.color_scheme else default_surface_color
    on_surface_color = page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else default_on_surface_color
    surface_variant_color = page.theme.color_scheme.surface_variant if page.theme and page.theme.color_scheme else default_surface_variant_color
    on_surface_variant_color = page.theme.color_scheme.on_surface_variant if page.theme and page.theme.color_scheme else default_on_surface_variant_color
    error_color = page.theme.color_scheme.error if page.theme and page.theme.color_scheme else default_error_color
    primary_container_color = page.theme.color_scheme.primary_container if page.theme and page.theme.color_scheme else default_primary_container_color

    def contact_card(text, icon_path, url, font_size=18):
        # Use relative path and check existence
        abs_icon_path = os.path.join(os.path.dirname(__file__), icon_path)
        icon_content = (
            ft.Image(src=icon_path, width=24, height=24, fit=ft.ImageFit.CONTAIN)
            if os.path.exists(abs_icon_path)
            else ft.Icon(
                ft.Icons.ERROR,
                color=error_color,
                size=24,
                tooltip=f"Icon not found: {icon_path}"
            )
        )

        def on_card_tap(e):
            try:
                page.launch_url(url)
            except Exception as ex:
                show_error_snackbar(page, f"Failed to open link: {ex}")

        card = ft.Container(
            width=360,
            height=60,
            bgcolor=surface_color,
            border_radius=16,
            border=ft.border.all(1, ft.Colors.with_opacity(0.1, on_surface_color)),
            padding=ft.padding.symmetric(horizontal=15, vertical=10),
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=8,
                color=ft.Colors.with_opacity(0.15, on_surface_color),
                offset=ft.Offset(0, 2),
            ),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        text,
                        size=font_size,
                        weight=ft.FontWeight.W_500,
                        color=on_surface_color,
                        no_wrap=True,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                    ft.Container(
                        width=40,
                        height=40,
                        gradient=ft.LinearGradient(
                            colors=[primary_color, primary_container_color],
                            begin=ft.alignment.top_left,
                            end=ft.alignment.bottom_right,
                        ),
                        border_radius=20,
                        alignment=ft.alignment.center,
                        content=icon_content,
                    ),
                ],
            ),
            on_click=on_card_tap,
        )

        def on_hover(e):
            card.bgcolor = (
                ft.Colors.with_opacity(0.05, primary_color)
                if e.data == "true"
                else surface_color
            )
            card.shadow.blur_radius = 12 if e.data == "true" else 8
            card.shadow.offset = ft.Offset(0, 4) if e.data == "true" else ft.Offset(0, 2)
            card.update()

        card.on_hover = on_hover
        return card

    image_content = (
        ft.Image(
            src="assets/home11.gif",
            border_radius=16,
            width=360,
            height=200,
            fit=ft.ImageFit.COVER,
        )
        if os.path.exists(os.path.join(os.path.dirname(__file__), "assets/home11.gif"))
        else ft.Container(
            width=360,
            height=200,
            bgcolor=surface_variant_color,
            border_radius=16,
            alignment=ft.alignment.center,
            content=ft.Text(
                "Image not available",
                color=on_surface_variant_color,
                size=16,
                weight=ft.FontWeight.W_500,
                text_align=ft.TextAlign.CENTER,
            ),
        )
    )

    return ft.Container(
        expand=True,
        padding=20,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(height=20),
                ft.Container(
                    content=image_content,
                    shadow=ft.BoxShadow(
                        spread_radius=1,
                        blur_radius=10,
                        color=ft.Colors.with_opacity(0.2, on_surface_color),
                    ),
                ),
                ft.Container(height=20),
                contact_card(
                    "Salah Abdeldaim",
                    "assets/facebook.png",
                    "https://www.facebook.com/share/16dTmEVH9x/",
                ),
                contact_card(
                    "01013243393",
                    "assets/whatsapp.png",
                    "https://wa.me/qr/3LLSAO65DGOXP1",
                ),
                contact_card(
                    "LinkedIn Profile",
                    "assets/linkedin.png",
                    "https://www.linkedin.com/in/salah-abdeldaim-226382264/",
                ),
                contact_card(
                    "salahabdeldaim609@gmail.com",
                    "assets/gmail.png",
                    "mailto:salahabdeldaim609@gmail.com",
                    font_size=14,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

def show_items_page(page: ft.Page, nav: ft.NavigationBar):
    current_dialog = None
    db_path = get_db_path(page)

    def dialog_func(item):
        nonlocal current_dialog
        item_id, name, type_name, qty, price, exp_month, exp_year = item
        expiry = f"{exp_month:02d}/{exp_year}"

        def close_dialog(e):
            nonlocal current_dialog
            try:
                e.page.dialog.open = False
                e.page.update()
                current_dialog = None
            except Exception as ex:
                logging.error(f"Error closing dialog: {ex}")
                show_error_snackbar(e.page, f"Error closing dialog: {ex}")

        def on_delete_click(e):
            try:
                conn = get_connection(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
                conn.close()

                close_dialog(e)
                show_success_snackbar(page, f"Item '{name}' deleted successfully")
                load_data()
                page.update()
            except Exception as ex:
                logging.error(f"Error deleting item: {ex}")
                show_error_snackbar(page, f"Error during deletion: {ex}")

        def on_edit_click(e):
            try:
                close_dialog(e)
                page.floating_action_button.visible = False
                body = page.controls[0]
                body.content = edit_item_page(page, db_path, item, nav)
                nav.selected_index = None
                page.update()
            except Exception as ex:
                logging.error(f"Error opening edit page: {ex}")
                show_error_snackbar(page, f"Error opening edit page: {ex}")

        main_rect = ft.Container(
            width=350,
            height=300,
            gradient=ft.LinearGradient(
                colors=[ft.Colors.WHITE, ft.Colors.BLUE_600],
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
            ),
            border_radius=24,
            padding=20,
            shadow=ft.BoxShadow(
                spread_radius=2,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            ),
            content=ft.Column(
                spacing=15,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.END,
                controls=[
                    ft.Text(f"Name: {name}", size=16, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Type: {type_name}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Quantity: {qty}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Price: {price:.2f}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Expiry Date: {expiry}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                ]
            )
        )

        dialog = ft.AlertDialog(
            title=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        "Item Details",
                        weight=ft.FontWeight.BOLD,
                        size=24,
                        color="#FFFFFF",
                        text_align=ft.TextAlign.RIGHT,
                    )
                ]
            ),
            content=main_rect,
            actions=[
                ft.ElevatedButton(
                    text="Close",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=close_dialog
                ),
                ft.ElevatedButton(
                    text="Delete",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.RED_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=on_delete_click
                ),
                ft.ElevatedButton(
                    text="Edit",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=on_edit_click
                )
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
            bgcolor=ft.Colors.TRANSPARENT,
            shape=ft.RoundedRectangleBorder(radius=24),
        )

        # إغلاق أي Dialog مفتوح قبل عرض الجديد
        if current_dialog is not None:
            try:
                page.dialog.open = False
                page.update()
                current_dialog = None
            except Exception as ex:
                logging.error(f"Error closing previous dialog: {ex}")

        current_dialog = dialog
        page.dialog = dialog
        dialog.open = True
        page.update()

        return dialog


    months = [str(i).zfill(2) for i in range(1, 13)]
    current_year = datetime.now().year
    years = [str(y) for y in range(current_year - 3, current_year + 8)]

    start_month = ft.Dropdown(
        label="Start Month",
        options=[ft.dropdown.Option(m) for m in months],
        expand=True,
    )

    start_year = ft.Dropdown(
        label="Start Year",
        options=[ft.dropdown.Option(y) for y in years],
        value=str(current_year),
        expand=True,
    )

    end_month = ft.Dropdown(
        label="End Month",
        options=[ft.dropdown.Option(m) for m in months],
        expand=True,
    )

    end_year = ft.Dropdown(
        label="End Year",
        options=[ft.dropdown.Option(y) for y in years],
        value=str(current_year),
        expand=True,
    )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("No", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Name", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Type", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Qty", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Price", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Expiry", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
        ],
        rows=[],
        column_spacing=10,
        heading_row_height=40,
        data_row_max_height=40,
        divider_thickness=1,
        bgcolor=page.theme.color_scheme.surface if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
    )

    def load_data():
        table.rows.clear()
        try:
            conn = get_connection(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT items.id, items.name, types.name_en, items.quantity, items.price,
                       items.expiry_month, items.expiry_year
                FROM items
                JOIN types ON items.type_id = types.id
                ORDER BY items.expiry_year ASC, items.expiry_month ASC
            """)
            items_data = cursor.fetchall()
            conn.close()

            def on_row_select(e, item):
                nonlocal current_dialog
                if hasattr(page, 'dialog') and page.dialog:
                    page.dialog.open = False
                    if page.dialog in page.overlay:
                        page.overlay.remove(page.dialog)
                new_dialog = dialog_func(item)
                if new_dialog not in page.overlay:
                    page.overlay.append(new_dialog)
                new_dialog.open = True
                page.update()

            if start_month.value and start_year.value and end_month.value and end_year.value:
                try:
                    start_date = datetime(int(start_year.value), int(start_month.value), 1)
                    end_date = datetime(int(end_year.value), int(end_month.value), 28)
                    filtered = [item for item in items_data if start_date <= datetime(item[6], item[5], 1) <= end_date]
                except Exception as ex:
                    logging.error(f"Error filtering data: {ex}")
                    filtered = items_data
            else:
                filtered = items_data

            for idx, item in enumerate(filtered, start=1):
                item_id, name, type_name, qty, price, exp_month, exp_year = item
                expiry = f"{exp_month:02d}/{exp_year}"
                table.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(idx), size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(name, size=11, max_lines=1, overflow="ellipsis", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(type_name, size=11, max_lines=1, overflow="ellipsis", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(str(qty), size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(f"{price:.2f}", size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(expiry, size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                        ],
                        selected=False,
                        on_select_changed=lambda e, it=item: on_row_select(e, it)
                    )
                )

            page.update()
        except Exception as ex:
            logging.error(f"Error loading data: {ex}")
            show_error_snackbar(page, f"Error loading data: {ex}")

    load_data()
    return ft.Container(
        expand=True,
        padding=10,
        content=ft.Column(
            [
                ft.ResponsiveRow(
                    [
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[start_month]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[start_year]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[end_month]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[end_year]),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            text="Apply Filter",
                            color=ft.Colors.WHITE,
                            bgcolor=page.theme.color_scheme.primary,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                elevation={"normal": 2, "hovered": 4, "pressed": 6},
                            ),
                            height=50,
                            expand=True,
                            on_click=lambda e: (
                                load_data(),
                                show_success_snackbar(page, "✅ Filter applied successfully!")
                            ),
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Container(
                    expand=True,
                    content=ft.ListView(
                        expand=True,
                        controls=[ft.Row([ft.Container(content=table, expand=True)], scroll="auto")],
                    ),
                ),
            ],
            expand=True,
            spacing=10,
        ),
    )

def edit_item_page(page: ft.Page, db_path: str, item, nav: ft.NavigationBar):
    item_id, name, type_name, qty, price, exp_month, exp_year = item

    name_field = ft.TextField(label="Item Name", value=name, expand=True, autofocus=True)
    quantity_field = ft.TextField(label="Quantity", value=str(qty), keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    price_field = ft.TextField(label="Price", value=str(price), keyboard_type=ft.KeyboardType.NUMBER, expand=True)

    months = [ft.dropdown.Option(str(i).zfill(2)) for i in range(1, 13)]
    current_year = datetime.now().year
    years = [ft.dropdown.Option(str(y)) for y in range(current_year - 3, current_year + 8)]

    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name_en, name_ar FROM types")
        medicine_types = cursor.fetchall()
        conn.close()
    except Exception as ex:
        logging.error(f"Error fetching medicine types: {ex}")
        show_error_snackbar(page, f"Error fetching types: {ex}")
        medicine_types = []

    type_id = None
    for t in medicine_types:
        if t[1] == type_name:
            type_id = str(t[0])
            break

    type_dropdown = ft.Dropdown(
        label="Type",
        options=[
            ft.dropdown.Option(key=str(t[0]), text=f"{t[1]} - {t[2]}")
            for t in medicine_types
        ],
        value=type_id,
        expand=True,
    )

    month_dropdown = ft.Dropdown(
        label="Expiry Month",
        options=months,
        value=str(exp_month).zfill(2),
        expand=True,
    )

    year_dropdown = ft.Dropdown(
        label="Expiry Year",
        options=years,
        value=str(exp_year),
        expand=True,
    )

    def save_item(e):
        try:
            if not name_field.value.strip():
                show_error_snackbar(page, "Please enter the item name")
                return

            if not quantity_field.value.isdigit() or int(quantity_field.value) <= 0:
                show_error_snackbar(page, "Quantity must be a positive integer")
                return

            if not price_field.value.replace(".", "", 1).isdigit() or float(price_field.value) <= 0:
                show_error_snackbar(page, "Price must be a valid positive number")
                return

            if not month_dropdown.value or not year_dropdown.value:
                show_error_snackbar(page, "Please select expiry month and year")
                return

            if not type_dropdown.value:
                show_error_snackbar(page, "Please select a medicine type")
                return

            conn = get_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE items
                SET name = ?, type_id = ?, quantity = ?, price = ?, expiry_month = ?, expiry_year = ?
                WHERE id = ?
                """,
                (
                    name_field.value.strip(),
                    int(type_dropdown.value),
                    int(quantity_field.value),
                    float(price_field.value),
                    int(month_dropdown.value),
                    int(year_dropdown.value),
                    item_id,
                )
            )
            conn.commit()
            conn.close()

            show_success_snackbar(page, "Item updated successfully")
            body = page.controls[0]
            body.content = show_items_page(page, nav)
            page.floating_action_button.visible = True
            nav.selected_index = 0
            page.update()
        except Exception as ex:
            logging.error(f"Error updating item: {ex}")
            show_error_snackbar(page, f"DB Error: {ex}")

    def cancel_edit(e):
        body = page.controls[0]
        body.content = show_items_page(page, nav)
        page.floating_action_button.visible = True
        nav.selected_index = 0
        page.update()

    return ft.Container(
        content=ft.Column(
            [
                name_field,
                quantity_field,
                price_field,
                ft.ResponsiveRow(
                    [
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[month_dropdown]),
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[year_dropdown]),
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[type_dropdown]),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "Save",
                            icon=ft.Icons.SAVE,
                            on_click=save_item,
                            expand=True,
                            bgcolor=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE,
                            color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
                        ),
                        ft.ElevatedButton(
                            "Cancel",
                            icon=ft.Icons.CANCEL,
                            on_click=cancel_edit,
                            expand=True,
                            bgcolor=ft.Colors.RED_600,
                            color=ft.Colors.WHITE,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        padding=20,
    )

def add_item_page(page: ft.Page, db_path: str, nav: ft.NavigationBar):
    name = ft.TextField(label="Item Name", expand=True, autofocus=True)
    quantity = ft.TextField(label="Quantity", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
    price = ft.TextField(label="Price", keyboard_type=ft.KeyboardType.NUMBER, expand=True)

    months = [ft.dropdown.Option(str(i).zfill(2)) for i in range(1, 13)]
    current_year = datetime.now().year
    current_month = datetime.now().month
    years = [ft.dropdown.Option(str(y)) for y in range(current_year - 3, current_year + 8)]

    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name_en, name_ar FROM types")
        medicine_types = cursor.fetchall()
        conn.close()
    except Exception as ex:
        logging.error(f"Error fetching medicine types: {ex}")
        show_error_snackbar(page, f"Error fetching types: {ex}")
        medicine_types = []

    type_dropdown = ft.Dropdown(
        label="Type",
        options=[
            ft.dropdown.Option(key=str(t[0]), text=f"{t[1]} - {t[2]}")
            for t in medicine_types
        ],
        expand=True,
    )

    month_dropdown = ft.Dropdown(
        label="Expiry Month",
        options=months,
        value=str(current_month).zfill(2),
        expand=True,
    )

    year_dropdown = ft.Dropdown(
        label="Expiry Year",
        options=years,
        value=str(current_year),
        expand=True,
    )

    def reset_fields():
        name.value = ""
        quantity.value = ""
        price.value = ""
        month_dropdown.value = str(current_month).zfill(2)
        year_dropdown.value = str(current_year)
        page.update()

    def save_item(e):
        try:
            if not name.value.strip():
                show_error_snackbar(page, "Please enter the item name")
                return

            if not quantity.value.isdigit() or int(quantity.value) <= 0:
                show_error_snackbar(page, "Quantity must be a positive integer")
                return

            if not price.value.replace(".", "", 1).isdigit() or float(price.value) <= 0:
                show_error_snackbar(page, "Price must be a valid positive number")
                return

            if not month_dropdown.value or not year_dropdown.value:
                show_error_snackbar(page, "Please select expiry month and year")
                return

            if not type_dropdown.value:
                show_error_snackbar(page, "Please select a medicine type")
                return

            conn = get_connection(db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO items (name, type_id, quantity, price, expiry_month, expiry_year)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name.value.strip(),
                    int(type_dropdown.value),
                    int(quantity.value),
                    float(price.value),
                    int(month_dropdown.value),
                    int(year_dropdown.value),
                )
            )
            conn.commit()
            conn.close()

            reset_fields()
            show_success_snackbar(page, "Item added successfully")
            body = page.controls[0]
            body.content = show_items_page(page, nav)
            page.floating_action_button.visible = True
            nav.selected_index = 0
            page.update()
        except Exception as ex:
            logging.error(f"Error saving item: {ex}")
            show_error_snackbar(page, f"DB Error: {ex}")

    def cancel_add(e):
        body = page.controls[0]
        body.content = show_items_page(page, nav)
        page.floating_action_button.visible = True
        nav.selected_index = 0
        page.update()

    return ft.Container(
        content=ft.Column(
            [
                name,
                quantity,
                price,
                ft.ResponsiveRow(
                    [
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[month_dropdown]),
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[year_dropdown]),
                        ft.Column(col={"xs": 12, "sm": 6}, controls=[type_dropdown]),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "Add",
                            icon=ft.Icons.SAVE,
                            on_click=save_item,
                            expand=True,
                            bgcolor=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE,
                            color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
                        ),
                        ft.ElevatedButton(
                            "Cancel",
                            icon=ft.Icons.CANCEL,
                            on_click=cancel_add,
                            expand=True,
                            bgcolor=ft.Colors.RED_600,
                            color=ft.Colors.WHITE,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        expand=True,
        padding=20,
    )

def export_page(page: ft.Page, nav: ft.NavigationBar, file_picker: ft.FilePicker):
    current_dialog = None
    db_path = get_db_path(page)

    def dialog_func(item):
        nonlocal current_dialog
        item_id, name, type_name, qty, price, exp_month, exp_year = item
        expiry = f"{exp_month:02d}/{exp_year}"

        def close_dialog(e):
            nonlocal current_dialog
            try:
                e.page.dialog.open = False
                e.page.update()
                current_dialog = None
            except Exception as ex:
                logging.error(f"Error closing dialog: {ex}")
                show_error_snackbar(e.page, f"Error closing dialog: {ex}")

        def on_delete_click(e):
            try:
                conn = get_connection(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
                conn.close()

                close_dialog(e)
                show_success_snackbar(page, f"Item '{name}' deleted successfully")
                load_data()
                page.update()
            except Exception as ex:
                logging.error(f"Error deleting item: {ex}")
                show_error_snackbar(page, f"Error during deletion: {ex}")

        def on_edit_click(e):
            try:
                close_dialog(e)
                page.floating_action_button.visible = False
                body = page.controls[0]
                body.content = edit_item_page(page, db_path, item, nav)
                nav.selected_index = None
                page.update()
            except Exception as ex:
                logging.error(f"Error opening edit page: {ex}")
                show_error_snackbar(page, f"Error opening edit page: {ex}")

        main_rect = ft.Container(
            width=350,
            height=300,
            gradient=ft.LinearGradient(
                colors=[ft.Colors.WHITE, ft.Colors.BLUE_600],
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
            ),
            border_radius=24,
            padding=20,
            shadow=ft.BoxShadow(
                spread_radius=2,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            ),
            content=ft.Column(
                spacing=15,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.END,
                controls=[
                    ft.Text(f"Name: {name}", size=16, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Type: {type_name}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Quantity: {qty}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Price: {price:.2f}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                    ft.Text(f"Expiry Date: {expiry}", size=14, text_align=ft.TextAlign.RIGHT, color=ft.Colors.BLACK),
                ]
            )
        )

        dialog = ft.AlertDialog(
            title=ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        "Item Details",
                        weight=ft.FontWeight.BOLD,
                        size=24,
                        color="#FFFFFF",
                        text_align=ft.TextAlign.RIGHT,
                    )
                ]
            ),
            content=main_rect,
            actions=[
                ft.ElevatedButton(
                    text="Close",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=close_dialog
                ),
                ft.ElevatedButton(
                    text="Delete",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.RED_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=on_delete_click
                ),
                ft.ElevatedButton(
                    text="Edit",
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600,
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=15,
                        elevation={"pressed": 2, "": 5},
                    ),
                    on_click=on_edit_click
                )
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
            bgcolor=ft.Colors.TRANSPARENT,
            shape=ft.RoundedRectangleBorder(radius=24),
        )

        # إغلاق أي Dialog مفتوح قبل عرض الجديد
        if current_dialog is not None:
            try:
                page.dialog.open = False
                page.update()
                current_dialog = None
            except Exception as ex:
                logging.error(f"Error closing previous dialog: {ex}")

        current_dialog = dialog
        page.dialog = dialog
        dialog.open = True
        page.update()

        return dialog

    months = [str(i).zfill(2) for i in range(1, 13)]
    current_year = datetime.now().year
    years = [str(y) for y in range(current_year - 3, current_year + 8)]

    start_month = ft.Dropdown(
        label="Start Month",
        options=[ft.dropdown.Option(m) for m in months],
        expand=True,
    )

    start_year = ft.Dropdown(
        label="Start Year",
        options=[ft.dropdown.Option(y) for y in years],
        value=str(current_year),
        expand=True,
    )

    end_month = ft.Dropdown(
        label="End Month",
        options=[ft.dropdown.Option(m) for m in months],
        expand=True,
    )

    end_year = ft.Dropdown(
        label="End Year",
        options=[ft.dropdown.Option(y) for y in years],
        value=str(current_year),
        expand=True,
    )

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("No", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Name", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Type", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Qty", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Price", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
            ft.DataColumn(ft.Text("Expiry", size=12, weight="bold", color=page.theme.color_scheme.on_surface if page.theme and page.theme.color_scheme else ft.Colors.BLACK)),
        ],
        rows=[],
        column_spacing=10,
        heading_row_height=40,
        data_row_max_height=40,
        divider_thickness=1,
        bgcolor=page.theme.color_scheme.surface if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
    )

    def load_data():
        table.rows.clear()
        try:
            conn = get_connection(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT items.id, items.name, types.name_en, items.quantity, items.price,
                       items.expiry_month, items.expiry_year
                FROM items
                JOIN types ON items.type_id = types.id
                ORDER BY items.expiry_year ASC, items.expiry_month ASC
            """)
            items_data = cursor.fetchall()
            conn.close()

            def on_row_select(e, item):
                nonlocal current_dialog
                if hasattr(page, 'dialog') and page.dialog:
                    page.dialog.open = False
                    if page.dialog in page.overlay:
                        page.overlay.remove(page.dialog)
                new_dialog = dialog_func(item)
                if new_dialog not in page.overlay:
                    page.overlay.append(new_dialog)
                new_dialog.open = True
                page.update()

            if start_month.value and start_year.value and end_month.value and end_year.value:
                try:
                    start_date = datetime(int(start_year.value), int(start_month.value), 1)
                    end_date = datetime(int(end_year.value), int(end_month.value), 28)
                    filtered = [item for item in items_data if start_date <= datetime(item[6], item[5], 1) <= end_date]
                except Exception as ex:
                    logging.error(f"Error filtering data: {ex}")
                    filtered = items_data
            else:
                filtered = items_data

            for idx, item in enumerate(filtered, start=1):
                item_id, name, type_name, qty, price, exp_month, exp_year = item
                expiry = f"{exp_month:02d}/{exp_year}"
                table.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(idx), size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(name, size=11, max_lines=1, overflow="ellipsis", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(type_name, size=11, max_lines=1, overflow="ellipsis", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(str(qty), size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(f"{price:.2f}", size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                            ft.DataCell(ft.Text(expiry, size=11, text_align="center", color=page.theme.color_scheme.on_surface if page.theme else ft.Colors.BLACK)),
                        ],
                        selected=False,
                        on_select_changed=lambda e, it=item: on_row_select(e, it)
                    )
                )

            page.update()
            return filtered  # Return filtered data for PDF export
        except Exception as ex:
            logging.error(f"Error loading data: {ex}")
            show_error_snackbar(page, f"Error loading data: {ex}")
            return []

    def export_to_pdf(e):
        try:
            filtered_data = load_data()
            if not filtered_data:
                show_error_snackbar(page, "No data to export")
                return
    
            def generate_pdf(pdf_path):
                try:
                    # read header info from DB
                    try:
                        conn_h = get_connection(db_path)
                        cur_h = conn_h.cursor()
                        cur_h.execute("SELECT pharmacy_name, phone_number, doctor_name, doctor_phone FROM settings WHERE id = 1")
                        header_row = cur_h.fetchone()
                        conn_h.close()
                    except Exception:
                        header_row = None

                    pharmacy_title = header_row[0] if header_row and header_row[0] else "My Pharmacy"
                    pharmacy_phone = header_row[1] if header_row and header_row[1] else ""
                    doctor_name_h = header_row[2] if header_row and len(header_row) > 2 and header_row[2] else ""
                    doctor_phone_h = header_row[3] if header_row and len(header_row) > 3 and header_row[3] else ""

                    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
                    styles = getSampleStyleSheet()
                    elems = []

                    # Header: pharmacy name (big), pharmacy phone, doctor name/phone
                    # register font and use if available
                    reg_font = _register_arabic_font()
                    title_style = styles['Title']
                    normal_style = styles['Normal']
                    if reg_font:
                        title_style.fontName = reg_font
                        normal_style.fontName = reg_font

                    # reshape text for Arabic if possible
                    display_title = _reshape_text_for_pdf(pharmacy_title)
                    display_phone = _reshape_text_for_pdf(pharmacy_phone)
                    display_doc_name = _reshape_text_for_pdf(doctor_name_h)
                    display_doc_phone = _reshape_text_for_pdf(doctor_phone_h)

                    # Centered header
                    title_para = Paragraph(f"<b>{display_title}</b>", title_style)
                    elems.append(title_para)
                    if display_phone:
                        elems.append(Paragraph(f"Phone: {display_phone}", normal_style))
                    if display_doc_name or display_doc_phone:
                        doc_line = ""
                        if display_doc_name:
                            doc_line += f"Doctor: {display_doc_name}"
                        if display_doc_phone:
                            if doc_line:
                                doc_line += f" — {display_doc_phone}"
                            else:
                                doc_line += f"Doctor phone: {display_doc_phone}"
                        elems.append(Paragraph(doc_line, normal_style))

                    elems.append(Spacer(1, 12))
                    # separator line
                    elems.append(Paragraph('<para alignment="center">' + ('—' * 60) + '</para>', normal_style))
                    elems.append(Spacer(1, 12))

                    data = [["No", "Name", "Type", "Qty", "Price", "Expiry"]]
                    for idx, item in enumerate(filtered_data, start=1):
                        item_id, name, type_name, qty, price, exp_month, exp_year = item
                        expiry = f"{exp_month:02d}/{exp_year}"
                        data.append([str(idx), name, type_name, str(qty), f"{price:.2f}", expiry])

                    # set column widths for better layout
                    table = Table(data, colWidths=[40, 180, 100, 50, 60, 70])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 12),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                        ('FONTNAME', (0, 1), (-1, -1), reg_font if reg_font else 'Helvetica'),
                        ('FONTSIZE', (0, 1), (-1, -1), 10),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ]))

                    elems.append(table)
                    doc.build(elems)
                    show_success_snackbar(page, f"✅ PDF saved in {pdf_path}")
                except Exception as ex:
                    logging.error(f"Error generating PDF: {ex}")
                    show_error_snackbar(page, f"Error generating PDF: {ex}")
    
            # لو أندرويد → خزّن في Downloads
            if page.platform == "android":
                save_dir = "/storage/emulated/0/Download"
                os.makedirs(save_dir, exist_ok=True)
                pdf_path = os.path.join(save_dir, f"items_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                generate_pdf(pdf_path)
    
            else:
                # ويندوز أو غيره → افتح FilePicker
                def on_result(ev: ft.FilePickerResultEvent):
                    if ev.path:
                        pdf_path = os.path.join(ev.path, f"items_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                        generate_pdf(pdf_path)
                    else:
                        show_error_snackbar(page, "❌ No folder selected")
    
                file_picker.on_result = on_result
                file_picker.get_directory_path(dialog_title="Select folder to save PDF")
                page.update()
    
        except Exception as ex:
            logging.error(f"Error initiating PDF export: {ex}")
            show_error_snackbar(page, f"Error initiating PDF export: {ex}")
    
    load_data()
    return ft.Container(
        expand=True,
        padding=10,
        content=ft.Column(
            [
                ft.ResponsiveRow(
                    [
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[start_month]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[start_year]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[end_month]),
                        ft.Column(col={"xs": 6, "sm": 3}, controls=[end_year]),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            text="Apply Filter",
                            color=ft.Colors.WHITE,
                            bgcolor=page.theme.color_scheme.primary,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                elevation={"normal": 2, "hovered": 4, "pressed": 6},
                            ),
                            height=50,
                            expand=True,
                            on_click=lambda e: (
                                load_data(),
                                show_success_snackbar(page, "✅ Filter applied successfully!")
                            ),
                        ),
                        ft.ElevatedButton(
                            text="Export as PDF",
                            color=ft.Colors.WHITE,
                            bgcolor=page.theme.color_scheme.primary,
                            style=ft.ButtonStyle(
                                shape=ft.RoundedRectangleBorder(radius=12),
                                elevation={"normal": 2, "hovered": 4, "pressed": 6},
                            ),
                            height=50,
                            expand=True,
                            on_click=export_to_pdf,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                ft.Container(
                    expand=True,
                    content=ft.ListView(
                        expand=True,
                        controls=[ft.Row([ft.Container(content=table, expand=True)], scroll="auto")],
                    ),
                ),
            ],
            expand=True,
            spacing=10,
        ),
    )

def settings_page(page: ft.Page):
    # Load settings from DB (use default values if any error)
    db_path = get_db_path(page)
    pharmacy_name = "My Pharmacy"
    phone_number = ""
    doctor_name = ""
    doctor_phone = ""
    theme_mode = "light"

    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode FROM settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            pharmacy_name = row[0] or pharmacy_name
            phone_number = row[1] or phone_number
            doctor_name = row[2] or doctor_name
            doctor_phone = row[3] or doctor_phone
            theme_mode = row[4] or theme_mode
        conn.close()
    except Exception as ex:
        logging.error(f"Error loading settings from DB: {ex}")

    name_field = ft.TextField(label="Pharmacy name", value=pharmacy_name, expand=True)
    phone_field = ft.TextField(label="Phone number", value=phone_number, expand=True)
    doctor_name_field = ft.TextField(label="Doctor name", value=doctor_name, expand=True)
    doctor_phone_field = ft.TextField(label="Doctor phone", value=doctor_phone, expand=True)

    theme_switch = ft.Switch(label="Dark mode", value=(theme_mode == "dark"))

    
    # Live update the appbar title while typing
    def _set_app_title(title: str):
        try:
            if hasattr(page, 'appbar') and page.appbar:
                page.appbar.title.value = title
                page.appbar.update()
        except Exception:
            pass

    def save_settings(e):
        nonlocal pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode
        pharmacy_name = name_field.value.strip() or pharmacy_name
        phone_number = phone_field.value.strip() or phone_number
        doctor_name = doctor_name_field.value.strip() or doctor_name
        doctor_phone = doctor_phone_field.value.strip() or doctor_phone
        theme_mode = "dark" if theme_switch.value else "light"

        try:
            conn = get_connection(db_path)
            cursor = conn.cursor()
            # ensure settings row exists
            cursor.execute("SELECT id FROM settings LIMIT 1")
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO settings (pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode) VALUES (?, ?, ?, ?, ?)", (pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode))
            else:
                cursor.execute("UPDATE settings SET pharmacy_name = ?, phone_number = ?, doctor_name = ?, doctor_phone = ?, theme_mode = ? WHERE id = 1", (pharmacy_name, phone_number, doctor_name, doctor_phone, theme_mode))
            conn.commit()
            conn.close()
            # update app title after saving
            _set_app_title(pharmacy_name)
            show_success_snackbar(page, "Settings saved")
        except Exception as ex:
            logging.error(f"Error saving settings: {ex}")
            show_error_snackbar(page, f"Error saving settings: {ex}")

    def reset_defaults(e):
        name_field.value = "My Pharmacy"
        phone_field.value = ""
        doctor_name_field.value = ""
        doctor_phone_field.value = ""
        # update UI and app title
        _set_app_title(name_field.value)
        page.update()

    # wire live update
    def _on_name_change(e):
        try:
            _set_app_title(name_field.value)
        except Exception:
            pass

    name_field.on_change = _on_name_change

    return ft.Container(
        expand=True,
        padding=20,
        content=ft.Column(
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD, color=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE),
                name_field,
                phone_field,
                doctor_name_field,
                doctor_phone_field,
                ft.Row([
                    ft.ElevatedButton("Save", on_click=save_settings, expand=True, bgcolor=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE, color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE),
                    ft.ElevatedButton("Reset", on_click=reset_defaults, expand=True, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            ]
        )
    )

def main(page: ft.Page):
    logging.info("Starting FarmaApp")
    page.rtl = False
    page.title = 'FarmaApp'
    page.window.width = 360
    page.window.height = 800
    page.window.top = 2
    page.window.left = 1000
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO

    try:
        db_path = get_db_path(page)
        logging.info(f"Database path: {db_path}")
        init_db(db_path)
        logging.info("Database initialized successfully")
    except Exception as ex:
        logging.error(f"Database initialization failed: {ex}")
        show_error_snackbar(page, f"Database error: {ex}")
        return

    # Load pharmacy name from DB (to set app title)
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT pharmacy_name FROM settings WHERE id = 1")
        row = cursor.fetchone()
        if row and row[0]:
            initial_pharmacy_name = row[0]
        else:
            initial_pharmacy_name = "FarmaApp"
        conn.close()
    except Exception as ex:
        logging.error(f"Error loading pharmacy_name at startup: {ex}")
        initial_pharmacy_name = "FarmaApp"

    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ft.Colors.BLUE,
            primary_container=ft.Colors.BLUE_100,
            secondary=ft.Colors.BLUE_200,
            secondary_container=ft.Colors.BLUE_50,
            surface=ft.Colors.WHITE,
            surface_variant=ft.Colors.GREY_100,
            on_surface=ft.Colors.BLACK,
            on_surface_variant=ft.Colors.GREY_800,
            error=ft.Colors.RED,
            on_error=ft.Colors.WHITE,
            on_error_container=ft.Colors.WHITE,
            on_primary=ft.Colors.WHITE,
            on_primary_container=ft.Colors.BLACK,
            background=ft.Colors.WHITE,
            on_background=ft.Colors.BLACK,
        ),
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )
    
    page.theme_mode = ft.ThemeMode.LIGHT

    logging.info("Theme initialized: %s", page.theme)
    logging.info("Color scheme: %s", page.theme.color_scheme)

    # Initialize FilePicker and add to page.overlay
    file_picker = ft.FilePicker()
    page.overlay.append(file_picker)
    page.update()

    body = ft.Container(expand=True)

    nav = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.LIST, label="View"),
            ft.NavigationBarDestination(icon=ft.Icons.UPLOAD, label="Export"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS, label="Settings"),
            ft.NavigationBarDestination(icon=ft.Icons.CONTACT_MAIL, label="Contact"),
        ],
        bgcolor=page.theme.color_scheme.surface if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
        indicator_color=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE,
        on_change=lambda e: update_page(e.control.selected_index),
    )

    def update_page(index: int):
        pages = [
            lambda p: show_items_page(p, nav),
            lambda p: export_page(p, nav, file_picker),
            settings_page,
            contact_page
        ]
        try:
            body.content = pages[index](page)
            nav.selected_index = index
            logging.info(f"Switched to page index: {index}")
            page.floating_action_button.visible = index == 0
            page.update()
        except Exception as ex:
            logging.error(f"Error loading page {index}: {ex}")
            show_error_snackbar(page, f"Error loading page: {ex}")

    def toggle_theme(e):
        page.theme_mode = (
            ft.ThemeMode.DARK if page.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        )
        page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(
                primary=ft.Colors.BLUE,
                primary_container=ft.Colors.BLUE_100,
                secondary=ft.Colors.BLUE_200,
                secondary_container=ft.Colors.BLUE_50,
                surface=ft.Colors.WHITE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.GREY_900,
                surface_variant=ft.Colors.GREY_100 if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.GREY_800,
                on_surface=ft.Colors.BLACK if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.WHITE,
                on_surface_variant=ft.Colors.GREY_800 if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.GREY_200,
                error=ft.Colors.RED,
                on_error=ft.Colors.WHITE,
                on_error_container=ft.Colors.WHITE,
                on_primary=ft.Colors.WHITE,
                on_primary_container=ft.Colors.BLACK,
                background=ft.Colors.WHITE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.GREY_900,
                on_background=ft.Colors.BLACK if page.theme_mode == ft.ThemeMode.LIGHT else ft.Colors.WHITE,
            ),
            use_material3=True,
            visual_density=ft.VisualDensity.COMFORTABLE,
        )
        nav.bgcolor = (
            page.theme.color_scheme.surface
            if page.theme and page.theme.color_scheme
            else ft.Colors.GREY_900 if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.WHITE
        )
        page.appbar.bgcolor = (
            page.theme.color_scheme.primary
            if page.theme and page.theme.color_scheme
            else ft.Colors.BLUE_600
        )
        page.appbar.title.color = (
            page.theme.color_scheme.on_primary
            if page.theme and page.theme.color_scheme
            else ft.Colors.WHITE
        )
        page.appbar.actions[0].icon_color = (
            page.theme.color_scheme.on_primary
            if page.theme and page.theme.color_scheme
            else ft.Colors.WHITE
        )
        nav.update()
        page.appbar.update()
        logging.info(f"Theme toggled to {page.theme_mode}")
        try:
            selected_index = nav.selected_index
            if selected_index is None or isinstance(selected_index, str) and not selected_index.isdigit():
                selected_index = 0
            update_page(int(selected_index))
        except Exception as ex:
            logging.error(f"Error reloading page after theme toggle: {ex}")
            update_page(0)
        page.update()

    page.appbar = ft.AppBar(
        title=ft.Text(
            initial_pharmacy_name,
            size=22,
            weight=ft.FontWeight.BOLD,
            color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
        ),
        center_title=True,
        bgcolor=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE_600,
        actions=[
            ft.IconButton(
                ft.Icons.BRIGHTNESS_6,
                on_click=toggle_theme,
                icon_color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
            )
        ],
    )

    def open_add_item(e):
        try:
            body.content = add_item_page(page, db_path, nav)
            logging.info("Opened add item page")
            nav.selected_index = None
            page.floating_action_button.visible = False
            page.update()
        except Exception as ex:
            logging.error(f"Error opening add item page: {ex}")
            show_error_snackbar(page, f"Error opening add item page: {ex}")

    page.floating_action_button = ft.FloatingActionButton(
        icon=ft.Icons.ADD,
        bgcolor=page.theme.color_scheme.primary if page.theme and page.theme.color_scheme else ft.Colors.BLUE_600,
        foreground_color=page.theme.color_scheme.on_primary if page.theme and page.theme.color_scheme else ft.Colors.WHITE,
        on_click=open_add_item,
    )

    try:
        body.content = show_items_page(page, nav)
        logging.info("Initial page set to show_items_page")
    except Exception as ex:
        logging.error(f"Error setting initial page: {ex}")
        show_error_snackbar(page, f"Error setting initial page: {ex}")

    try:
        page.add(body, nav)
        logging.info("Layout elements added to page")
    except Exception as ex:
        logging.error(f"Error adding layout elements: {ex}")
        show_error_snackbar(page, f"Error adding layout: {ex}")

    page.update()

ft.app(target=main, assets_dir=os.path.join(os.path.dirname(__file__), "assets"))