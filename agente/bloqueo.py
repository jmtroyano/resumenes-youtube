"""Bloqueo único para el repositorio local.

Evita que la app escriba archivos mientras git está sincronizando (pull/rebase),
y viceversa. Es reentrante, así que una operación puede anidar otras.
"""
import threading

repo = threading.RLock()
