"""Shared colours and a flat button helper."""
import tkinter as tk

KEY = "#010101"          # the transparent colour of the cartoon windows (matches tools/build_sprites.py)
CREAM = "#FBF6EE"
INK = "#33313F"
SOFT = "#6B6879"
ACCENT = "#B9532F"
ACCENT_ACTIVE = "#A24526"
BUTTON = "#F0E6D6"
BUTTON_ACTIVE = "#E6D8C2"
BORDER = "#D9C9B0"
FONT = "Segoe UI"


def make_button(parent, text, command, primary=False, small=False, **kw):
    size = 9 if small else 10
    return tk.Button(
        parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
        font=(FONT, size, "bold" if primary else "normal"),
        bg=ACCENT if primary else BUTTON, fg="white" if primary else INK,
        activebackground=ACCENT_ACTIVE if primary else BUTTON_ACTIVE,
        activeforeground="white" if primary else INK,
        padx=10 if small else 14, pady=4 if small else 6, **kw)
