__copyright__ = "Copyright (C) 2024  Angelo Tata"
__license__ = "GNU GPLv2"

# Standard library
import json
import re

from collections import namedtuple
from dataclasses import InitVar, dataclass, field
from datetime import date
from decimal import Decimal

# Third party
from beancount.core import account as bc_account
from beancount.core import data as bc_data
from beancount.core import getters as bc_getters

__plugins__ = ("auto_ratios",)

# Third party
from beancount.core.data import Directive, Entries, Options

# Metadata keys must begin with a lowercase character from a-z
# and may contain (uppercase or lowercase) letters, numbers,
# dashes and underscores.
RE_META_KEY = re.compile(r"^[a-z][\w\-]*$")

RATIO_DIRECTIVE_TYPE = "Ratio"
DEFAULT_RATIO_KEY = "ratio"

ConfigError = namedtuple("ConfigError", "source message entry")


@dataclass
class Config:
    """Class holding the configuration for this plugin.

    The format for the configuration string is a JSON object of the form:
    {
      "shared_accounts": ["account_1", "account_2],
      "partner_account": "another_account",
      "ratio_key": "a_metadata_key"
    }

    Examples:
    - {
        "joint_accounts": ["Assets:UK:Monzo:Joint", "Assets:UK:Octopus:Cash"],
        "partner_expenses": "Assets:Partner:Expenses",
        "ratio_key": "ratio"
    }
    - {
        "joint_accounts": ["Assets:UK:Monzo:Joint"],
        "partner_expenses": "Assets:Partner:Expenses"
    }
    """

    shared_accounts: list[str] = field(init=False)
    partner_account: str = field(init=False)
    raw_config: InitVar[str]
    ratio_metadata_key: str = DEFAULT_RATIO_KEY

    def __post_init__(self, raw_config: str):
        config = json.loads(raw_config.replace("'", '"'))

        self.shared_accounts = config["shared_accounts"]
        self.partner_account = config["partner_account"]

        for _account in [*self.shared_accounts, self.partner_account]:
            if not (bc_account.is_valid(_account)):
                raise ValueError(f"at least one of the accounts provided ({_account}) is not in a recognised format")

        if (ratio_metadata_key := config.get("ratio_metadata_key")) is not None:
            if RE_META_KEY.match(ratio_metadata_key) is None:
                raise ValueError(
                    f"the 'ratio' metadata name ({ratio_metadata_key}) is not valid. "
                    "See https://beancount.github.io/docs/beancount_language_syntax.html#metadata_1"
                )
            self.ratio_metadata_key = ratio_metadata_key


@dataclass
class Ratio:
    value: Decimal
    start_date: date
    end_date: date


def parse_ratio(entry: bc_data.Custom) -> Ratio:
    """Parses a custom Ratio entry and returns a Ratio class instance.

    The format for these entries is:
    <start_date> custom "Ratio" <ratio> <optional_end_date>

    Examples:
        - 2021-01-01 custom "Ratio" 0.58 "20231231"
        - 2022-06-01 custom "Ratio" 0.8
        - 2024-06-01 custom "Ratio" 1

    @param entry: an entry in the format above
    @return:
    """
    if len(entry.values) < 1 or len(entry.values) > 2:
        raise ValueError(f"This directive requires one or two arguments ({len(entry.values)} were given)")

    # Each value in `entry.values` is a NamedTuple
    # called ValueType, holding both the actual value and its type.
    ratio_percentage = entry.values[0][0]

    if not entry.values[0][1] == Decimal:
        raise ValueError(
            f"The ratio percentage ({ratio_percentage}) must be a Decimal. It was '{entry.values[0][1]}' instead"
        )

    ratio_start_date = entry.date
    ratio_end_date = date.fromisoformat(entry.values[1][0]) if len(entry.values) > 1 else date.today()

    return Ratio(
        ratio_percentage,
        ratio_start_date,
        ratio_end_date,
    )


def is_split_transaction(entry: bc_data.Transaction, config: Config) -> bool:
    """Returns True for split transactions, False otherwise

    A transaction is identified as split if there is at least one posting using the
    provided shared account and one posting using the partner's account.
    """
    entry_accounts = bc_getters.get_entry_accounts(entry)
    return any(account in config.shared_accounts for account in entry_accounts) and any(
        account == config.partner_account for account in entry_accounts
    )


def is_eligible(posting: bc_data.Posting, config: Config) -> bool:
    """Returns True if a posting is not attached to either the provided shared account or the partner account"""
    return posting.account not in [*config.shared_accounts, config.partner_account]


def add_metadata(entry: Directive, config: Config, ratios: list[Ratio]):
    if isinstance(entry, bc_data.Custom) and entry.type == RATIO_DIRECTIVE_TYPE:
        ratios.append(parse_ratio(entry))
    elif isinstance(entry, bc_data.Transaction):
        if is_split_transaction(entry, config):
            for posting in entry.postings:
                if not is_eligible(posting, config):
                    continue

                for ratio in ratios:
                    if ratio.start_date <= entry.date <= ratio.end_date:
                        posting.meta[config.ratio_metadata_key] = ratio.value
                        break

    return entry


def auto_ratios(entries: Entries, options_map: Options, raw_config: str):
    """Adds metadata to transactions that are being split with a partner.

    The metadata is based on custom Ratio entries parsed by the plugin.
    Ratio entries with overlapping dates are not handled specially:
    the first one including a given transaction will be used to assign the ratio.

    Args:
      entries: A list of directives.
      options_map: A dict of options parsed from the file (unused here).
      raw_config: a configuration string (see the Config class docstring for details)
    Returns:
      A tuple of entries and errors.
    """
    ratios = []
    augmented_entries = []
    errors = []

    try:
        config = Config(raw_config)
        augmented_entries = [add_metadata(entry, config, ratios) for entry in entries]
    except ValueError as v:
        errors.append(ConfigError(bc_data.new_metadata("<auto_ratios>", 0), f"Invalid configuration: {v}", None))

    return augmented_entries, errors
