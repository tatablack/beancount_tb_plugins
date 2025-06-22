# beancount-tb-plugins
This is a collection of plugins for the beancount accounting software.

## auto_ratio
In the context of a shared (joint) bank account, typically with one's partner, it is often the case that contributions
are not based on an even split. For that reason, expenses from that account should be split based on the ratio of the
contributions, which may change over time based on personal circumstances (e.g. one person getting a salary increase).

This plugin allows to define a ratio for an account, valid in a certain time period, and then automatically adds
metadata to transactions involving that account.

## noduplicates_extended
This builds on the official `noduplicates` plugin to take into account metadata (from a transaction and its postings).
This avoids false positives in the `noduplicates` plugin, by expanding the criteria used to differentiate transactions.

My own use case: a joint account with my partner, which we use to pay for public transport. When going out together,
our bank would generate almost identical transactions (same amount, date and time, payee, etc.), which can only be
distinguished by the metadata (e.g. the card used for the transaction).