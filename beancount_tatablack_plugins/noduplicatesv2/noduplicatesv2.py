"""This plugin validates that there are no duplicate transactions.
"""
__copyright__ = "Copyright (C) 2024  Angelo Tata"
__license__ = "GNU GPLv2"


# Standard library
import collections

from typing import Any, NamedTuple

# Third party
import xxhash

from beancount.core import data

__plugins__ = ('validate_no_duplicates_v2',)

ConfigError = collections.namedtuple('ConfigError', 'source message entry')
CompareError = collections.namedtuple('CompareError', 'source message entry')

IGNORED_FIELD_NAMES = {'meta', 'diff_amount'}


# plugin "noduplicatesv2" "{
#   'include_meta': ['paid_by']
# }"
def validate_no_duplicates_v2(entries, unused_options_map, config_str):
    """Check that the entries are unique, by computing hashes.

    Args:
      entries: A list of directives.
      unused_options_map: An options map.
      config_str: A configuration string.
    Returns:
      A list of new errors, if any were found.
    """
    # pylint: disable=eval-used
    errors = []

    config_obj = eval(config_str, {}, {})
    if not isinstance(config_obj, dict):
        errors.append(ConfigError(
            data.new_metadata('<validate_no_duplicates_v2>', 0),
            "Invalid configuration for validate_no_duplicates_v2 plugin; skipping.", None))
        return entries, errors

    unused_hashes, errors = hash_entries(entries, config_obj)
    print(unused_hashes)
    return entries, errors


def custom_hash_function(objtuple: NamedTuple, config_obj: dict[str, Any]):
    """Hash the given namedtuple and its child fields.

    This iterates over all the members of objtuple, skipping the attributes from
    the 'ignore' set, and computes a unique hash string code. If the elements
    are lists or sets, sorts them for stability.

    Args:
      objtuple: A tuple object or other.
      ignore: A set of strings, attribute names to be skipped in
        computing a stable hash. For instance, circular references to objects
        or irrelevant data.

    """
    hash_obj = xxhash.xxh3_64()

    for attr_name, attr_value in zip(objtuple._fields, objtuple):
        if attr_name == 'diff_amount':
            continue
        elif attr_name == 'meta':
            # Documentation about the shape of metadata can be found here:
            # https://beancount.github.io/docs/beancount_language_syntax.html#metadata_1
            sub_hashes = []

            for k, v in attr_value.items():
                if k in config_obj.get("include_meta"):
                    subhash_obj = xxhash.xxh3_64()
                    subhash_obj.update(str(v).encode())
                    sub_hashes.append(subhash_obj.hexdigest())

            for subhash in sorted(sub_hashes):
                hash_obj.update(subhash.encode())
        elif isinstance(attr_value, (list, set, frozenset)):
            sub_hashes = []
            for element in attr_value:
                if isinstance(element, tuple):
                    sub_hashes.append(custom_hash_function(element, config_obj))
                else:
                    subhash_obj = xxhash.xxh3_64()
                    subhash_obj.update(str(element).encode())
                    sub_hashes.append(subhash_obj.hexdigest())
            for subhash in sorted(sub_hashes):
                hash_obj.update(subhash.encode())
        else:
            hash_obj.update(str(attr_value).encode())

    return hash_obj.hexdigest()


def hash_entries(entries, config_obj: dict[str, Any]):
    """Compute unique hashes of each of the entries and return a map of them.

    This is used for comparisons between sets of entries.

    Args:
      entries: A list of directives.
    Returns:
      A dict of hash-value to entry (for all entries) and a list of errors.
      Errors are created when duplicate entries are found.
    """
    entry_hash_dict = {}
    errors = []
    num_legal_duplicates = 0
    for entry in entries:
        hash_ = custom_hash_function(entry, config_obj)

        if hash_ in entry_hash_dict:
            if isinstance(entry, data.Price):
                # Note: Allow duplicate Price entries, they should be common
                # because of the nature of stock markets (if they're closed, the
                # data source is likely to return an entry for the previously
                # available date, which may already have been fetched).
                num_legal_duplicates += 1
            else:
                other_entry = entry_hash_dict[hash_]
                errors.append(
                    CompareError(entry.meta,
                                 "Duplicate entry: {} == {}".format(entry, other_entry),
                                 entry))
        entry_hash_dict[hash_] = entry

    if not errors:
        assert len(entry_hash_dict) + num_legal_duplicates == len(entries), (
            len(entry_hash_dict), len(entries), num_legal_duplicates)
    return entry_hash_dict, errors
