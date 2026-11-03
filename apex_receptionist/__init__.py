"""Apex receptionist domain package.

Framework-independent business logic for conversations, bookings, AI answers,
and tenant-scoped receptionist data. HTTP adapters (Flask today, Django views
later) call into this package and must not reimplement the FSM.
"""
