use anchor_lang::prelude::*;

use crate::{constants::*, error::ErrorCode, state::{Config, Mark}};

/// Everything a publisher asserts about one company, in one message.
///
/// The publisher computes these off-chain from public markets. The program's
/// job is not to trust the numbers but to refuse the ones that cannot be true,
/// and to stamp the rest with a time and a slot nobody can backdate.
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct PublishArgs {
    pub company: String,
    pub kind: u8,
    pub token_price_micro: u64,
    pub token_implied_cents: u64,
    pub crowd_value_cents: u64,
    pub crowd_low_cents: u64,
    pub crowd_high_cents: u64,
    pub crowd_per_token_micro: u64,
    pub p_event_bps: u16,
    pub open_top_mass_bps: u16,
    pub next_deadline: i64,
    pub next_deadline_bps: u16,
    pub source_read_at: i64,
    pub sources_hash: [u8; 32],
}

#[event]
pub struct MarkPublished {
    pub publisher: Pubkey,
    pub symbol: String,
    pub crowd_value_cents: u64,
    pub token_implied_cents: u64,
    pub p_event_bps: u16,
    pub source_read_at: i64,
    pub published_at: i64,
}

/// Publishing is open. The program does not ask who you are, it asks whether the
/// reading can be true: fresh, inside its own stated range, newer than the one
/// stored, and carrying a hash of the inputs behind it. A feed only one key can
/// refresh dies the day that key stops.
#[derive(Accounts)]
#[instruction(symbol: String)]
pub struct Publish<'info> {
    #[account(mut)]
    pub publisher: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        init_if_needed,
        payer = publisher,
        space = 8 + Mark::INIT_SPACE,
        seeds = [MARK_SEED, symbol.as_bytes()],
        bump
    )]
    pub mark: Account<'info, Mark>,
    pub system_program: Program<'info, System>,
}

fn valid_symbol(symbol: &str) -> bool {
    !symbol.is_empty()
        && symbol.len() <= 12
        && symbol.bytes().all(|b| b.is_ascii_uppercase())
}

pub fn handle_publish(ctx: Context<Publish>, symbol: String, args: PublishArgs) -> Result<()> {
    require!(valid_symbol(&symbol), ErrorCode::InvalidSymbol);
    require!(
        !args.company.is_empty() && args.company.len() <= 24,
        ErrorCode::InvalidCompany
    );
    require!(args.kind <= 1, ErrorCode::InvalidKind);

    // Probabilities are shares of one, never more.
    for bps in [args.p_event_bps, args.open_top_mass_bps, args.next_deadline_bps] {
        require!(bps <= BPS_DENOMINATOR, ErrorCode::ProbabilityOutOfRange);
    }

    // Prices must be real. A zero here would read as free rather than unknown.
    require!(args.token_price_micro > 0, ErrorCode::ValueNotPositive);
    require!(args.token_implied_cents > 0, ErrorCode::ValueNotPositive);

    // A listing mark carries a crowd value and its range; a private valuation
    // mark carries odds instead, so its value fields are allowed to be empty.
    if args.kind == 0 {
        require!(args.crowd_value_cents > 0, ErrorCode::ValueNotPositive);
        require!(args.crowd_per_token_micro > 0, ErrorCode::ValueNotPositive);
        require!(
            args.crowd_low_cents <= args.crowd_high_cents,
            ErrorCode::RangeInverted
        );
        require!(
            args.crowd_value_cents >= args.crowd_low_cents
                && args.crowd_value_cents <= args.crowd_high_cents,
            ErrorCode::ValueOutsideRange
        );
    }

    let clock = Clock::get()?;
    let now = clock.unix_timestamp;
    require!(
        args.source_read_at <= now + MAX_CLOCK_SKEW_SECONDS,
        ErrorCode::ReadingFromTheFuture
    );
    require!(
        now - args.source_read_at <= MAX_READING_AGE_SECONDS,
        ErrorCode::ReadingTooOld
    );

    let mark = &mut ctx.accounts.mark;
    // A freshly created account has an empty symbol, and publishing always sets
    // one. Do not use a timestamp as the sentinel: a chain whose clock reads
    // zero would make every publication look like the first, and the rule below
    // would never run.
    let first_time = mark.symbol.is_empty();
    // A feed that can be rewound is not a feed. Each reading must be newer
    // than the one it replaces.
    require!(
        first_time || args.source_read_at > mark.source_read_at,
        ErrorCode::NotNewerThanStored
    );

    mark.symbol = symbol.clone();
    mark.company = args.company;
    mark.kind = args.kind;
    mark.token_price_micro = args.token_price_micro;
    mark.token_implied_cents = args.token_implied_cents;
    mark.crowd_value_cents = args.crowd_value_cents;
    mark.crowd_low_cents = args.crowd_low_cents;
    mark.crowd_high_cents = args.crowd_high_cents;
    mark.crowd_per_token_micro = args.crowd_per_token_micro;
    mark.p_event_bps = args.p_event_bps;
    mark.open_top_mass_bps = args.open_top_mass_bps;
    mark.next_deadline = args.next_deadline;
    mark.next_deadline_bps = args.next_deadline_bps;
    mark.source_read_at = args.source_read_at;
    mark.published_at = now;
    mark.published_slot = clock.slot;
    mark.sources_hash = args.sources_hash;
    mark.last_publisher = ctx.accounts.publisher.key();
    mark.publish_count = mark.publish_count.saturating_add(1);
    mark.bump = ctx.bumps.mark;

    if first_time {
        ctx.accounts.config.mark_count = ctx.accounts.config.mark_count.saturating_add(1);
    }

    emit!(MarkPublished {
        publisher: ctx.accounts.publisher.key(),
        symbol,
        crowd_value_cents: mark.crowd_value_cents,
        token_implied_cents: mark.token_implied_cents,
        p_event_bps: mark.p_event_bps,
        source_read_at: mark.source_read_at,
        published_at: mark.published_at,
    });
    Ok(())
}
