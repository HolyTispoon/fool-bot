"""
The Codex games on the web (docs/pbd-site.md; docs/design/pbd-site.md):
what the publisher writes, as the Codex cog's frontend beside Discord.

A package the cog calls, not a mixin: it holds no Discord state and
decides no rule. `record` is the publisher's own file, `shapes` the JSON
it writes into the bucket, `segments` a line of the model's as the web
draws it, `queue` the sends off the click's path, and `config` whether
this process publishes at all.
"""
