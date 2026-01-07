import re
from collections.abc import AsyncIterator
from typing import TypedDict
from uuid import UUID

from rapidfuzz import fuzz

from ynab_cli.adapters import ynab
from ynab_cli.adapters.ynab import models, util
from ynab_cli.adapters.ynab.api.payees import get_payees, update_payee
from ynab_cli.adapters.ynab.api.transactions import get_transactions_by_payee
from ynab_cli.domain import ports
from ynab_cli.domain.constants import UNUSED_PREFIX
from ynab_cli.domain.progress_state import ProgressState
from ynab_cli.domain.rate_limiter import RateLimitExceeded, RateLimiter
from ynab_cli.domain.settings import Settings


def _should_skip_payee(payee: models.Payee) -> bool:
    if (
        payee.deleted
        or (payee.transfer_account_id and isinstance(payee.transfer_account_id, str))
        or payee.name.startswith("Transfer : ")
        or payee.name.startswith(UNUSED_PREFIX)
        or payee.name in ["Starting Balance", "Manual Balance Adjustment", "Reconciliation Balance Adjustment"]
    ):
        return True
    return False


# Known acronyms that should stay uppercase
KNOWN_ACRONYMS = {
    "AAA", "ABC", "ACME", "ALS", "AMC", "AMEX", "ARCO", "ASICS", "ASUS", "AT&T", "ATM", "ATP", "AWS", "AXS",
    "BAPE", "BC", "BFW", "BLM", "BMW", "BOOX",
    "CD", "CPA", "CVS",
    "DHL", "DK", "DR", "DHT",
    "EC", "ER",
    "FAO", "FLOR", "FREE",
    "GU",
    "HBO", "HOA",
    "IPIC", "IRS", "II", "III",
    "JD", "JR",
    "KFC", "KI", "KUHL", "KÜHL",
    "LARQ", "LT", "LLC", "LTD",
    "MTA", "MoPOP",
    "NBC", "NK", "NW", "NY", "NYC", "NYS", "NZXT",
    "OAS", "OPC", "OWC",
    "PC", "PCC", "PETCO", "PGA", "PIM", "PIT", "PNW", "PNWF", "POC", "PS", "PURE", "PVR",
    "QFC",
    "RAM", "RATP", "REI", "REST", "ROAD", "RS", "RSVP",
    "SAAS", "SAM", "SKNV", "SMRTFT", "SNAXX", "SP", "SPEAR", "SSENSE", "SSP",
    "TMJ", "TRMNL", "TT", "TWG", "TV",
    "UGG", "UK", "UPS", "US", "USA", "USPS", "UW",
    "VIA", "VIP", "VRBO", "VSCO", "VW",
    "WAMU", "WH", "WSDOT",
    "YALE", "YMCA", "YNAB",
}

# Known CamelCase brand names
CAMELCASE_BRANDS = {
    # Number-prefixed brands
    "1password": "1Password",
    "7-eleven": "7-Eleven",
    # CamelCase brands A-Z
    "actblue": "ActBlue",
    "abmat": "AbMat",
    "amazonfresh": "AmazonFresh",
    "appfolio": "AppFolio",
    "appicons": "AppIcons",
    "bakedeco": "BakeDeco",
    "bonbon": "BonBon",
    "bofa": "BofA",
    "bridgeclimb": "BridgeClimb",
    "cashzone": "CashZone",
    "cellartracker": "CellarTracker",
    "centurylink": "CenturyLink",
    "chargerback": "ChargerBack",
    "copystop": "CopyStop",
    "dexafit": "DexaFit",
    "doordash": "DoorDash",
    "evpassport": "EVPassport",
    "familymart": "FamilyMart",
    "famzoo": "FamZoo",
    "fringesport": "FringeSport",
    "getrael": "GetRael",
    "giftya": "GiftYa",
    "gofan": "GoFan",
    "gofundme": "GoFundMe",
    "goodsnooze": "GoodSnooze",
    "gopuff": "goPuff",
    "homeagain": "HomeAgain",
    "homepay": "HomePay",
    "iphone": "iPhone",
    "ipad": "iPad",
    "imac": "iMac",
    "itunes": "iTunes",
    "legalzoom": "LegalZoom",
    "lemlem": "LemLem",
    "linkedin": "LinkedIn",
    "macstories": "MacStories",
    "mcdonald": "McDonald",
    "mcgilvra": "McGilvra",
    "mclaughlin": "McLaughlin",
    "mopop": "MoPOP",
    "mytorch": "MyTorch",
    "netjets": "NetJets",
    "newegg": "NewEgg",
    "noodletools": "NoodleTools",
    "ohsnap": "OhSnap",
    "omarknows": "OmarKnows",
    "oneblade": "OneBlade",
    "onemedical": "OneMedical",
    "pacsun": "PacSun",
    "parkmobile": "ParkMobile",
    "parkwhiz": "ParkWhiz",
    "paypal": "PayPal",
    "petsmart": "PetSmart",
    "photoday": "PhotoDay",
    "picobrew": "PicoBrew",
    "popflash": "PopFlash",
    "printfresh": "PrintFresh",
    "rockcreek": "RockCreek",
    "seatac": "SeaTac",
    "spothero": "SpotHero",
    "stockx": "StockX",
    "superduper": "SuperDuper",
    "tiktok": "TikTok",
    "trueandco": "TrueandCo",
    "tunnelbear": "TunnelBear",
    "ubreakifix": "UbreakIFix",
    "upwork": "UpWork",
    "urbancred": "UrbanCred",
    "wepay": "WePay",
    "youtube": "YouTube",
    # Lowercase-start brands
    "ebay": "eBay",
    "ecompanystore": "eCompanyStore",
    "etrailer": "eTrailer",
    "lululemon": "lululemon",
    "minialley": "miniAlley",
    "prana": "prAna",
}

# Small words that should stay lowercase (except at start of name)
SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "via", "with"}

# State and country abbreviations (2 letters)
STATE_COUNTRY_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
    "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
    "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
    "UK", "US", "EU", "AU", "NZ", "SA", "UAE",
}


def _normalize_name(name: str) -> str:
    """Normalize a payee name with smart capitalization.

    Handles:
    - Known acronyms (IRS, ATM, HBO, etc.) - preserved uppercase
    - CamelCase brand names (PayPal, YouTube, etc.) - preserved
    - Small words (of, and, the, etc.) - lowercase except at start
    - State/country codes (WA, NY, UK) - preserved uppercase
    - Possessives ('s) - properly formatted
    - Domain TLDs (.com, .org) - lowercase
    """
    # Strip and normalize whitespace first
    name = re.sub(r"\s+", " ", name.strip())

    if not name:
        return name

    words = name.split()
    result_words = []

    for i, word in enumerate(words):
        # Check if it's a domain (contains a dot) - likely a website
        if "." in word and not word.endswith("."):
            # Handle things like "ATP.fm" or "Paddle.net*" or "PAYEE.COM"
            parts = re.split(r"(\.\w+)", word)
            normalized_parts = []
            for part in parts:
                if part.startswith("."):
                    # TLD - keep lowercase
                    normalized_parts.append(part.lower())
                else:
                    # For domain names, force title case (don't treat as acronym)
                    normalized_parts.append(_normalize_word(part, i, len(words), is_domain=True))
            result_words.append("".join(normalized_parts))
        elif word.endswith(("'s", "'S", "'s", "'S")):
            # Handle possessives - normalize the base word, keep 's lowercase
            base = word[:-2]
            normalized_base = _normalize_word(base, i, len(words))
            result_words.append(f"{normalized_base}'s")
        else:
            result_words.append(_normalize_word(word, i, len(words)))

    return " ".join(result_words)


def _normalize_word(word: str, position: int, total_words: int, is_domain: bool = False) -> str:
    """Normalize a single word based on context and known patterns.

    Args:
        word: The word to normalize
        position: Position in the sentence (0-indexed)
        total_words: Total number of words
        is_domain: If True, don't preserve unknown acronyms (force title case)
    """
    # Strip any punctuation for checking, but preserve it
    stripped = word.strip("*(),;:!?\"'")
    prefix = word[: len(word) - len(word.lstrip("*(),;:!?\"'"))]
    suffix = word[len(word.rstrip("*(),;:!?\"'")) :]

    # Check for known acronyms (case-insensitive check, preserve uppercase)
    if stripped.upper() in KNOWN_ACRONYMS:
        return prefix + stripped.upper() + suffix

    # Check for state/country codes (typically 2 uppercase letters)
    if stripped.upper() in STATE_COUNTRY_CODES:
        return prefix + stripped.upper() + suffix

    # Check for known CamelCase brands
    lower_stripped = stripped.lower()
    # Check both exact match and prefix match (for things like "PayPal's")
    for brand_lower, brand_proper in CAMELCASE_BRANDS.items():
        if lower_stripped == brand_lower:
            return prefix + brand_proper + suffix
        if lower_stripped.startswith(brand_lower):
            remainder = stripped[len(brand_lower) :]
            return prefix + brand_proper + remainder.lower() + suffix

    # Check for small words (only if not first word)
    if position > 0 and stripped.lower() in SMALL_WORDS:
        return prefix + stripped.lower() + suffix

    # Check if it's all uppercase with length > 1 (might be an unknown acronym)
    # But only if it's short (<=5 chars) to avoid ALL CAPS names
    # Skip this check for domain names (e.g., PAYEE.COM should become Payee.com)
    if not is_domain and stripped.isupper() and 1 < len(stripped) <= 5 and stripped.isalpha():
        return prefix + stripped + suffix

    # Check for ordinals like "1st", "2nd", "3rd", "24H"
    if re.match(r"^\d+(st|nd|rd|th|h)$", stripped, re.IGNORECASE):
        return prefix + stripped[:-1] + stripped[-1].upper() + suffix

    # Check for Roman numerals
    if re.match(r"^[IVXLCDM]+$", stripped.upper()) and len(stripped) <= 4:
        return prefix + stripped.upper() + suffix

    # Handle words starting with numbers (e.g., "1Password", "3D", "7-Eleven")
    # Find where letters start and capitalize from there
    match = re.match(r"^(\d+[-]?)(.*)$", stripped)
    if match:
        num_prefix, rest = match.groups()
        if rest:
            # Capitalize the letter part
            return prefix + num_prefix + rest.capitalize() + suffix
        # Just a number, return as-is
        return prefix + stripped + suffix

    # Default: title case
    return prefix + stripped.capitalize() + suffix


class NormalizeNamesParams(TypedDict):
    dry_run: bool


class NormalizeNames:
    """Use case for normalizing payee names."""

    def __init__(self, io: ports.IO, client: ynab.AuthenticatedClient):
        self._io = io
        self._client = client

    async def __call__(
        self, settings: Settings, params: NormalizeNamesParams
    ) -> AsyncIterator[tuple[models.Payee, str]]:
        try:
            progress_total = 0

            payees = (
                await util.get_asyncio_detailed(
                    self._io, get_payees.asyncio_detailed, settings.ynab.budget_id, client=self._client
                )
            ).data.payees
            payees.sort(key=lambda p: p.name)

            progress_total = len(payees)
            await self._io.progress.update(total=progress_total)
            for payee in payees:
                await self._io.progress.update(advance=1)

                if _should_skip_payee(payee=payee):
                    continue

                normalized_name = _normalize_name(payee.name)
                if normalized_name != payee.name:
                    yield (payee, normalized_name)

                    if not params["dry_run"]:
                        await util.run_asyncio_detailed(
                            self._io,
                            update_payee.asyncio_detailed,
                            settings.ynab.budget_id,
                            str(payee.id),
                            client=self._client,
                            body=models.PatchPayeeWrapper(payee=models.SavePayee(name=normalized_name)),
                        )

        except Exception as e:
            if isinstance(e, util.ApiError) and e.status_code == 401:
                await self._io.print("Invalid or expired access token. Please update your settings.")
            elif isinstance(e, util.ApiError) and e.status_code == 429:
                await self._io.print("API rate limit exceeded. Try again later, or get a new access token.")
            else:
                await self._io.print(f"Exception when calling YNAB: {e}")
        finally:
            await self._io.progress.update(total=progress_total, completed=progress_total)


# Suffixes to strip for comparison - these don't help identify unique payees
STRIP_SUFFIXES = {
    "inc", "inc.", "llc", "llc.", "co", "co.", "company", "corp", "corp.", "corporation", "ltd", "ltd.",
}

# Articles and short words to skip when finding meaningful first word
SKIP_WORDS = {"the", "a", "an", "la", "le", "el", "il", "de", "da", "di", "du", "van", "von", "&"}


def _strip_suffix(name: str) -> str:
    """Remove corporate suffixes like Inc, LLC, etc."""
    words = name.lower().split()
    while len(words) > 1 and words[-1] in STRIP_SUFFIXES:
        words = words[:-1]
    return " ".join(words)


def _get_core_words(name: str) -> list[str]:
    """Get core words from a name, skipping articles."""
    words = name.lower().split()
    return [w for w in words if w not in SKIP_WORDS and w not in STRIP_SUFFIXES and len(w) > 0]


def _are_likely_duplicates(name1: str, name2: str) -> bool:
    """Determine if two payee names are likely duplicates.

    Uses EXTREMELY STRICT matching to minimize false positives. Better to miss
    many true duplicates than to have any false positives.

    The ONLY ways to match:
    1. Exact match after stripping corporate suffixes
    2. First TWO core words EXACTLY match (when both have 2+ words)
    3. For single-word names: exact first word match AND ≥95% similarity

    Args:
        name1: First payee name (normalized, lowercased)
        name2: Second payee name (normalized, lowercased)

    Returns:
        True if the names are likely duplicates
    """
    # Strip corporate suffixes for comparison
    stripped1 = _strip_suffix(name1)
    stripped2 = _strip_suffix(name2)

    # Strategy 1: Exact match after stripping
    if stripped1 == stripped2:
        return True

    # Get core words (excluding articles and suffixes)
    words1 = _get_core_words(name1)
    words2 = _get_core_words(name2)

    # If either has no core words, can't reliably compare
    if not words1 or not words2:
        return False

    # Determine how many words must match based on name lengths
    min_words = min(len(words1), len(words2))

    if min_words >= 2:
        # Both names have 2+ words: first TWO words must match exactly
        # This eliminates: "Cafe Flora" vs "Cafe Florian", "Google Storage" vs "Google Store"
        if words1[0] != words2[0] or words1[1] != words2[1]:
            return False

        # First two words match! Check if one is a prefix of the other
        shorter = words1 if len(words1) <= len(words2) else words2
        longer = words1 if len(words1) > len(words2) else words2

        # If shorter is an exact prefix of longer, it's a duplicate
        # e.g., "Four Seasons" is prefix of "Four Seasons Lanai"
        if longer[: len(shorter)] == shorter:
            return True

        # Otherwise require very high similarity
        overall_ratio = fuzz.token_sort_ratio(stripped1, stripped2)
        return overall_ratio >= 92

    else:
        # One or both names are single words: require exact match + very high similarity
        # This handles: "Bose" vs "Bose Corporation"
        if words1[0] != words2[0]:
            return False

        overall_ratio = fuzz.token_sort_ratio(stripped1, stripped2)
        return overall_ratio >= 95


class ListDuplicatesParams(TypedDict):
    pass


class ListDuplicates:
    """Use case for listing duplicate payees.

    Uses multiple strategies to identify likely duplicates while minimizing false positives:
    - Strips common suffixes (Restaurant, Parking, Store, etc.)
    - Checks first word similarity
    - Uses token-based fuzzy matching
    - Requires high similarity thresholds
    """

    def __init__(self, io: ports.IO, client: ynab.AuthenticatedClient):
        self._io = io
        self._client = client

    async def __call__(
        self, settings: Settings, params: ListDuplicatesParams
    ) -> AsyncIterator[tuple[models.Payee, models.Payee]]:
        try:
            progress_total = 0

            possible_duplicates: dict[tuple[UUID, str], list[tuple[UUID, str]]] = {}

            payees = (
                await util.get_asyncio_detailed(
                    self._io, get_payees.asyncio_detailed, settings.ynab.budget_id, client=self._client
                )
            ).data.payees
            payees.sort(key=lambda p: p.name)

            progress_total = len(payees)
            await self._io.progress.update(total=progress_total)
            for idx, payee in enumerate(payees):
                await self._io.progress.update(advance=1)

                if _should_skip_payee(payee=payee):
                    continue

                filtered_payees = list(payees)
                del filtered_payees[idx]

                for filtered_payee in filtered_payees:
                    if _should_skip_payee(payee=filtered_payee):
                        continue

                    normalized_payee_name = _normalize_name(payee.name).lower()
                    normalized_filtered_payee_name = _normalize_name(filtered_payee.name).lower()

                    if _are_likely_duplicates(normalized_payee_name, normalized_filtered_payee_name):
                        # Check to see if we already tracked this possible duplicate in the other direction
                        existing_possible_duplicates = possible_duplicates.get((filtered_payee.id, filtered_payee.name))
                        if existing_possible_duplicates:
                            if (payee.id, payee.name) in existing_possible_duplicates:
                                continue

                        possible_duplicates[(payee.id, payee.name)] = possible_duplicates.get(
                            (payee.id, payee.name), []
                        )
                        possible_duplicates[(payee.id, payee.name)].append((filtered_payee.id, filtered_payee.name))

                        yield (payee, filtered_payee)

        except Exception as e:
            if isinstance(e, util.ApiError) and e.status_code == 401:
                await self._io.print("Invalid or expired access token. Please update your settings.")
            elif isinstance(e, util.ApiError) and e.status_code == 429:
                await self._io.print("API rate limit exceeded. Try again later, or get a new access token.")
            else:
                await self._io.print(f"Exception when calling YNAB: {e}")
        finally:
            await self._io.progress.update(total=progress_total, completed=progress_total)


class ListUnusedParams(TypedDict, total=False):
    dry_run: bool
    prefix_unused: bool
    start_from: str | None  # Start from a letter (e.g., "B") or payee name (e.g., "Bo Concept")
    auto_resume: bool  # Resume from last saved progress
    auto_wait: bool  # Automatically wait when rate limited instead of stopping


class ListUnused:
    """Use case for listing unused payees.

    This operation is expensive because it checks transactions for each payee.
    It supports:
    - Rate limiting to respect YNAB's 200 requests/hour limit
    - Progress persistence to resume after rate limiting or interruption
    - Starting from a specific letter or payee name
    """

    def __init__(self, io: ports.IO, client: ynab.AuthenticatedClient):
        self._io = io
        self._client = client

    def _should_start_from(self, payee_name: str, start_from: str) -> bool:
        """Check if we should start processing from this payee.

        Args:
            payee_name: The name of the payee to check.
            start_from: The starting letter or payee name prefix.

        Returns:
            True if we should start processing from this payee.
        """
        # Case-insensitive comparison
        payee_name_lower = payee_name.lower()
        start_from_lower = start_from.lower()

        # If start_from is a single letter, check if payee starts with it
        if len(start_from) == 1:
            return payee_name_lower >= start_from_lower

        # Otherwise, treat as a prefix match for the full name
        return payee_name_lower >= start_from_lower

    async def __call__(self, settings: Settings, params: ListUnusedParams) -> AsyncIterator[models.Payee]:
        rate_limiter = RateLimiter()
        progress_state = ProgressState("list_unused_payees", settings.ynab.budget_id)

        # Get parameters with defaults
        dry_run = params.get("dry_run", False)
        prefix_unused = params.get("prefix_unused", False)
        start_from = params.get("start_from")
        auto_resume = params.get("auto_resume", False)
        auto_wait = params.get("auto_wait", False)

        # Callbacks for auto-wait progress updates
        async def on_wait_start(total_seconds: float) -> None:
            minutes = int(total_seconds // 60)
            seconds = int(total_seconds % 60)
            await self._io.print(f"\n⏳ Rate limit reached. Auto-waiting {minutes}m {seconds}s until quota resets...")
            await self._io.print("   (Progress is saved - you can safely Ctrl+C and resume later with --auto-resume)")

        async def on_wait_progress(elapsed: float, remaining: float) -> None:
            elapsed_min = int(elapsed // 60)
            remaining_min = int(remaining // 60)
            remaining_sec = int(remaining % 60)
            await self._io.print(f"   ⏳ Waited {elapsed_min}m, {remaining_min}m {remaining_sec}s remaining...")

        # Load saved progress if auto_resume is enabled
        if auto_resume and progress_state.load():
            await self._io.print(progress_state.get_resume_info())
            await self._io.print(f"\n{rate_limiter.get_status_message()}\n")

        try:
            progress_total = 0

            # Show initial rate limiter status
            await self._io.print(rate_limiter.get_status_message())

            # Acquire a slot for the initial payees request
            await rate_limiter.acquire(
                auto_wait=auto_wait,
                on_wait_start=on_wait_start if auto_wait else None,
                on_wait_progress=on_wait_progress if auto_wait else None,
            )

            payees = (
                await util.get_asyncio_detailed(
                    self._io, get_payees.asyncio_detailed, settings.ynab.budget_id, client=self._client
                )
            ).data.payees
            payees.sort(key=lambda p: p.name)

            progress_total = len(payees)
            progress_state.total_items = progress_total
            await self._io.progress.update(total=progress_total)

            # Determine the starting point
            start_index = 0
            if auto_resume and progress_state.last_processed_index >= 0:
                start_index = progress_state.last_processed_index + 1
                await self._io.print(f"Resuming from index {start_index} ({progress_state.last_processed_name})")
            elif start_from:
                # Find the starting index based on start_from
                for idx, payee in enumerate(payees):
                    if self._should_start_from(payee.name, start_from):
                        start_index = idx
                        await self._io.print(f"Starting from '{payee.name}' (index {idx})")
                        break
                else:
                    await self._io.print(f"No payees found starting from '{start_from}'")

            # Update progress bar to reflect starting point
            if start_index > 0:
                await self._io.progress.update(completed=start_index)

            for idx, payee in enumerate(payees):
                # Skip until we reach the starting point
                if idx < start_index:
                    continue

                await self._io.progress.update(advance=1)

                if _should_skip_payee(payee=payee):
                    progress_state.update(
                        name=payee.name,
                        index=idx,
                        increment_processed=True,
                        increment_unused=False,
                    )
                    continue

                # Check rate limit before making the API call
                try:
                    await rate_limiter.acquire(
                        auto_wait=auto_wait,
                        on_wait_start=on_wait_start if auto_wait else None,
                        on_wait_progress=on_wait_progress if auto_wait else None,
                    )
                except RateLimitExceeded as e:
                    # Save progress before stopping
                    progress_state.save()
                    await self._io.print(f"\n{e}")
                    await self._io.print(f"\nProgress saved. Run with --auto-resume to continue from '{payee.name}'.")
                    await self._io.print(f"Or use --start-from '{payee.name}' to manually resume.")
                    return

                transactions = (
                    await util.get_asyncio_detailed(
                        self._io,
                        get_transactions_by_payee.asyncio_detailed,
                        settings.ynab.budget_id,
                        str(payee.id),
                        client=self._client,
                    )
                ).data.transactions
                num_transactions = len(transactions)

                is_unused = not num_transactions

                # Update progress state
                progress_state.update(
                    name=payee.name,
                    index=idx,
                    increment_processed=True,
                    increment_unused=is_unused,
                )

                # List unused payee if no transactions
                if is_unused:
                    if prefix_unused:
                        payee.name = f"{UNUSED_PREFIX} {payee.name}"

                    yield payee

                    # If prefix_unused is True, rename the payee
                    if not dry_run and prefix_unused:
                        try:
                            await rate_limiter.acquire(
                                auto_wait=auto_wait,
                                on_wait_start=on_wait_start if auto_wait else None,
                                on_wait_progress=on_wait_progress if auto_wait else None,
                            )
                            await util.run_asyncio_detailed(
                                self._io,
                                update_payee.asyncio_detailed,
                                settings.ynab.budget_id,
                                str(payee.id),
                                client=self._client,
                                body=models.PatchPayeeWrapper(payee=models.SavePayee(name=payee.name)),
                            )
                        except RateLimitExceeded as e:
                            progress_state.save()
                            await self._io.print(f"\n{e}")
                            await self._io.print(f"\nProgress saved. Payee '{payee.name}' was NOT renamed.")
                            return
                        except Exception as e:
                            await self._io.print(f"Failed to rename payee {payee.name}: {e}")

                # Periodically show rate limit status
                if progress_state.processed_count % 20 == 0:
                    await self._io.print(rate_limiter.get_status_message())

            # Operation completed successfully - print summary then clear saved progress
            await self._io.print(
                f"\nCompleted! Found {progress_state.unused_count} unused payees out of {progress_total} total."
            )
            await self._io.print(rate_limiter.get_status_message())
            progress_state.clear()

        except Exception as e:
            # Save progress on any error
            progress_state.save()

            if isinstance(e, util.ApiError) and e.status_code == 401:
                await self._io.print("Invalid or expired access token. Please update your settings.")
            elif isinstance(e, util.ApiError) and e.status_code == 429:
                await self._io.print("API rate limit exceeded. Progress saved.")
                await self._io.print(f"Run with --auto-resume to continue from '{progress_state.last_processed_name}'.")
            else:
                await self._io.print(f"Exception when calling YNAB: {e}")
                await self._io.print(f"Progress saved at '{progress_state.last_processed_name}'.")
        finally:
            await self._io.progress.update(total=progress_total, completed=progress_total)


class ListAllParams(TypedDict):
    pass


class ListAll:
    """Use case for listing all payees."""

    def __init__(self, io: ports.IO, client: ynab.AuthenticatedClient):
        self._io = io
        self._client = client

    async def __call__(self, settings: Settings, params: ListAllParams) -> AsyncIterator[models.Payee]:
        try:
            progress_total = 0

            payees = (
                await util.get_asyncio_detailed(
                    self._io, get_payees.asyncio_detailed, settings.ynab.budget_id, client=self._client
                )
            ).data.payees
            payees.sort(key=lambda p: p.name)

            progress_total = len(payees)
            await self._io.progress.update(total=progress_total)
            for payee in payees:
                await self._io.progress.update(advance=1)

                if _should_skip_payee(payee=payee):
                    continue

                yield payee

        except Exception as e:
            if isinstance(e, util.ApiError) and e.status_code == 401:
                await self._io.print("Invalid or expired access token. Please update your settings.")
            elif isinstance(e, util.ApiError) and e.status_code == 429:
                await self._io.print("API rate limit exceeded. Try again later, or get a new access token.")
            else:
                await self._io.print(f"Exception when calling YNAB: {e}")
        finally:
            await self._io.progress.update(total=progress_total, completed=progress_total)
