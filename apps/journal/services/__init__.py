"""Journal services.

Deliberately empty: `simple_edit` reaches into `apps.bank_feed.services` (feed rows,
transfer mirrors), and `apps.bank_feed` imports from `apps.journal` in turn -- the
shared line writer, `lines`, among it. Re-exporting anything here would pull that
edge up to module-import time and turn a one-directional dependency into a cycle.
"""
