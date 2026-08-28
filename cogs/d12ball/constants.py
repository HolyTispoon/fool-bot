"""
The cog's own two module-level constants.

They live apart from the mixins because more than one of them reads
each, and a constant defined in whichever mixin happened to use it
first is a mixin the others import for a number.
"""

# The most placements one run back may make before it is treated as
# stuck. Twelve players a side is the whole board several times over,
# so this only ever fires on a bug -- see continue_run_back.
MAX_RUN_BACK_PASSES = 60


# The highest the clock may be set to by hand. The clock itself has no
# ceiling -- it runs for as long as a last possession does -- so this is
# not a rule, only what two digits hold: everything that prints the
# clock does so as `{:02d}`, and `/d12ball time 100` would be the one
# state the scoreboard cannot draw.
MAX_DEBUG_CLOCK = 99

