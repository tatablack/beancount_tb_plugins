"""This plugin validates that there are no duplicate transactions."""

__copyright__ = "Copyright (C) 2025  Angelo Tata"
__license__ = "GNU GPLv2"

# Standard library
import collections
import json

from dataclasses import InitVar, dataclass, field
from typing import NamedTuple

# Third party
import xxhash

from beancount.core import data

__plugins__ = ("validate_no_duplicates_extended",)

ConfigError = collections.namedtuple("ConfigError", "source message entry")
CompareError = collections.namedtuple("CompareError", "source message entry")


@dataclass
class Config:
    """Class holding the configuration for this plugin.

    The format for the configuration string is a JSON object of the form:
    {
       "include_meta": ["some_metadata_key"]
    }
    """

    raw_config: InitVar[str]
    include_meta: list[str] = field(init=False)

    def __post_init__(self, raw_config: str):
        config = json.loads(raw_config.replace("'", '"'))

        if "include_meta" in config and not isinstance(config["include_meta"], list):
            raise ValueError("The `include_meta` parameter must be a list")

        self.include_meta = config.get("include_meta", [])


def _is_namedtuple_instance(obj):
    return isinstance(obj, tuple) and hasattr(obj, "_fields") and hasattr(obj, "_asdict")


def validate_no_duplicates_extended(entries, unused_options_map, raw_config: str):
    """Check that the entries are unique, by computing hashes.

    If no configuration is provided, this effectively behaves like the standard
    noduplicates plugin: it will ignore an entry's metadata when computing its
    hash for comparing it with other entries.

    However, a configuration may specify if any metadata key/value pairs
    should instead be used in the hash computation.

    Example usage:
    plugin "beancount_tatablack_plugins.noduplicates_extended" "{
        'include_meta': ['paid_by']
    }"

    Args:
      entries: A list of directives.
      unused_options_map: A dict of options parsed from the file (unused here).
      raw_config: a configuration string (see the Config class docstring for details)
    Returns:
      A tuple of entries and errors.
    """
    # pylint: disable=eval-used
    errors = []

    try:
        config = Config(raw_config)
    except ValueError:
        errors.append(
            ConfigError(
                data.new_metadata("<validate_no_duplicates_extended>", 0),
                "Invalid configuration for validate_no_duplicates_extended plugin; skipping.",
                None,
            )
        )
        return entries, errors

    _, errors = hash_entries(entries, config)
    return entries, errors


def custom_hash_function(hash_obj: xxhash.xxh3_64, objtuple: NamedTuple, config: Config):
    """Hash the given namedtuple and its child fields.

    This iterates over all the members of objtuple, skipping certain attributes,
    and computes a unique hash string code. If the elements are lists or sets,
    sorts them for stability.

    Args:
      objtuple: A tuple object or other.
      config: this plugin's configuration
    """
    for attr_name, attr_value in zip(objtuple._fields, objtuple):
        if attr_name == "diff_amount":
            continue
        elif attr_name == "meta":
            # Documentation about the shape of metadata can be found here:
            # https://beancount.github.io/docs/beancount_language_syntax.html#metadata_1
            sub_hashes = []

            subhash_obj = xxhash.xxh3_64()
            for k, v in attr_value.items():
                if k in config.include_meta:
                    subhash_obj.update(str(v).encode())
                    sub_hashes.append(subhash_obj.hexdigest())
                    subhash_obj.reset()

            for subhash in sorted(sub_hashes):
                hash_obj.update(subhash.encode())
        elif isinstance(attr_value, (list, set, frozenset)):
            sub_hashes = []
            subhash_obj = xxhash.xxh3_64()
            for element in attr_value:
                if _is_namedtuple_instance(element):
                    sub_hashes.append(custom_hash_function(subhash_obj, element, config))
                else:
                    subhash_obj.update(str(element).encode())
                    sub_hashes.append(subhash_obj.hexdigest())
                subhash_obj.reset()

            for subhash in sorted(sub_hashes):
                hash_obj.update(subhash.encode())
        else:
            hash_obj.update(str(attr_value).encode())

    return hash_obj.hexdigest()


def hash_entries(entries, config: Config):
    """Compute unique hashes of each of the entries and return a map of them.

    This is used for comparisons between sets of entries.

    Args:
      entries: A list of directives.
      config: this plugin's configuration
    Returns:
      A dict of hash-value to entry (for all entries) and a list of errors.
      Errors are created when duplicate entries are found.
    """
    entry_hash_dict = {}
    errors = []
    num_legal_duplicates = 0
    hash_obj = xxhash.xxh3_64()

    for entry in entries:
        hash_ = custom_hash_function(hash_obj, entry, config)

        if hash_ in entry_hash_dict:
            if isinstance(entry, data.Price):
                # Note: Allow duplicate Price entries, they should be common
                # because of the nature of stock markets (if they're closed, the
                # data source is likely to return an entry for the previously
                # available date, which may already have been fetched).
                num_legal_duplicates += 1
            else:
                other_entry = entry_hash_dict[hash_]
                errors.append(CompareError(entry.meta, "Duplicate entry: {} == {}".format(entry, other_entry), entry))
        entry_hash_dict[hash_] = entry
        hash_obj.reset()

    if not errors:
        assert len(entry_hash_dict) + num_legal_duplicates == len(entries), (
            len(entry_hash_dict),
            len(entries),
            num_legal_duplicates,
        )
    return entry_hash_dict, errors
