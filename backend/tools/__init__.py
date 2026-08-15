"""Development tools that are not part of the running application.

Nothing under `app/` imports anything here. This exists so that the demo-data
generator can be unit tested like any other pure module, rather than living in
a script where it could only be checked by running it and looking.
"""
