use anchor_lang::prelude::*;

#[constant]
pub const CONFIG_SEED: &[u8] = b"config";

#[constant]
/// Bumped when the account layout changes, since a stored account cannot grow.
pub const MARK_SEED: &[u8] = b"mark.v2";

/// A basis point scale. Any probability published must fall within it.
#[constant]
pub const BPS_DENOMINATOR: u16 = 10_000;

/// How far ahead of the chain's clock a reading may claim to be, to absorb
/// clock skew between the publisher and the validator without letting a
/// publisher post a reading from the future.
#[constant]
pub const MAX_CLOCK_SKEW_SECONDS: i64 = 120;

/// How old a market reading may be at the moment it is published. Older than
/// this and the publisher should read the markets again rather than post it.
#[constant]
pub const MAX_READING_AGE_SECONDS: i64 = 3_600;
