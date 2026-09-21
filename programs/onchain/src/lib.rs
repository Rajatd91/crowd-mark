//! An on-chain reference price for private companies.
//!
//! Pyth and Chainlink price public stocks. Nothing on Solana prices a company
//! that has not listed, so tokenised claims on Anthropic, OpenAI and the rest
//! trade against a mark their own issuer publishes off-chain, or against
//! nothing at all.
//!
//! This feed publishes a value derived from markets anyone can check: the
//! prediction markets where people bet real money on whether and at what value
//! these companies list. Each mark carries the reading time, the publishing
//! slot, the probability behind it, how much of it rests on an assumption, and
//! a hash of its inputs, so a reader can judge it rather than trust it.
pub mod constants;
pub mod error;
pub mod instructions;
pub mod state;

use anchor_lang::prelude::*;

pub use constants::*;
pub use instructions::*;
pub use state::*;

declare_id!("6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU");

#[program]
pub mod onchain {
    use super::*;

    /// Open the feed. The payer becomes its authority.
    pub fn initialize(ctx: Context<Initialize>, publisher: Pubkey) -> Result<()> {
        crate::instructions::initialize::handle_initialize(ctx, publisher)
    }

    /// Rotate the keeper key that is allowed to publish.
    pub fn set_publisher(ctx: Context<SetPublisher>, publisher: Pubkey) -> Result<()> {
        crate::instructions::set_publisher::handle_set_publisher(ctx, publisher)
    }

    /// Publish one company's mark, creating its account the first time.
    pub fn publish(ctx: Context<Publish>, symbol: String, args: PublishArgs) -> Result<()> {
        crate::instructions::publish::handle_publish(ctx, symbol, args)
    }
}
