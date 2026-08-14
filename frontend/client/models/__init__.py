"""Qt item models.

An item model sits between data and a view: it answers "how many rows?" and
"what belongs in this cell?", and the view asks. Keeping them in their own
package rather than in `widgets/` reflects what they are — neither a widget nor
a screen, but the adapter between the two.
"""
