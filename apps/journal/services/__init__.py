"""Journal services.

Deliberately empty: `simple_edit` reaches into `apps.bank_feed.services` for the
shared line writer, and `apps.bank_feed` imports from `apps.journal` in turn.
Re-exporting anything here would pull that edge up to module-import time and turn
a one-directional dependency into a cycle.
"""
