# -*- coding: utf-8 -*-

from metagpt.actions import Action


class FixBug(Action):
    """Fix bug action without any implementation details"""

    name: str = "FixBug"
