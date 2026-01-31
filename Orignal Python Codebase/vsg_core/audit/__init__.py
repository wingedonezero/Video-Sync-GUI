# vsg_core/audit/__init__.py
# -*- coding: utf-8 -*-
"""
Pipeline audit trail system for debugging timing issues.

Creates a persistent JSON file that tracks EVERY timing-related value
at each pipeline step. Never overwrites - only appends/adds new keys.
"""
from .trail import AuditTrail

__all__ = ['AuditTrail']
