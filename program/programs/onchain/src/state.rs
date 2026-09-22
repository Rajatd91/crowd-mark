use anchor_lang::prelude::*;

/// Who is allowed to publish, and how many companies have ever been published.
///
/// The authority owns the feed. The publisher is the keeper key that runs on a
/// schedule, so the owner never has to keep a hot key.
#[account]
#[derive(InitSpace)]
pub struct Config {
    pub authority: Pubkey,
    pub publisher: Pubkey,
    pub mark_count: u32,
    pub bump: u8,
}

/// What a private company is worth, according to markets anyone can check.
///
/// Money is stored in fixed units so no float ever touches the chain: company
/// values in whole cents, per-token prices in millionths of a dollar. A market
/// cap of $3.75T is 375_000_000_000_000 cents, well inside u64.
///
/// `sources_hash` is a SHA-256 over the exact inputs the publisher read, which
/// makes a mark checkable: anyone can re-read the same public markets for
/// `source_read_at`, recompute, and compare.
#[account]
#[derive(InitSpace)]
pub struct Mark {
    /// Ticker of the tokenised claim, for example ANTHROPIC.
    #[max_len(12)]
    pub symbol: String,
    /// The company the claim refers to.
    #[max_len(24)]
    pub company: String,
    /// 0 = the crowd prices a listing, 1 = the crowd prices a private valuation.
    pub kind: u8,

    /// Traded price of one token, in millionths of a dollar.
    pub token_price_micro: u64,
    /// What that token price implies the whole company is worth, in cents.
    pub token_implied_cents: u64,

    /// What the crowd expects the company to be worth, in cents.
    pub crowd_value_cents: u64,
    /// The same value if the open-ended top bracket were valued differently.
    pub crowd_low_cents: u64,
    pub crowd_high_cents: u64,
    /// The crowd's value expressed per token, in millionths of a dollar.
    pub crowd_per_token_micro: u64,

    /// Probability the event happens at all, in basis points.
    pub p_event_bps: u16,
    /// Probability sitting in the open-ended top bracket, in basis points. The
    /// larger this is, the more of the value is assumption rather than market.
    pub open_top_mass_bps: u16,
    /// The nearest meaningful deadline the crowd prices, and its probability.
    pub next_deadline: i64,
    pub next_deadline_bps: u16,

    /// When the publisher read the markets, and when the chain accepted it.
    pub source_read_at: i64,
    pub published_at: i64,
    pub published_slot: u64,
    /// SHA-256 of the inputs behind this mark.
    pub sources_hash: [u8; 32],
    /// Who last refreshed this mark, and how many times it has been refreshed.
    /// Anyone may publish, so the feed records who did rather than who was allowed.
    pub last_publisher: Pubkey,
    pub publish_count: u32,
    pub bump: u8,
}

impl Mark {
    /// A mark is only worth reading if it was published recently. Consumers
    /// should treat anything older than this as stale rather than trust it.
    pub const MAX_AGE_SECONDS: i64 = 6 * 60 * 60;

    pub fn is_stale(&self, now: i64) -> bool {
        now.saturating_sub(self.published_at) > Self::MAX_AGE_SECONDS
    }
}
