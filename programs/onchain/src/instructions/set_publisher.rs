use anchor_lang::prelude::*;

use crate::{constants::*, error::ErrorCode, state::Config};

#[derive(Accounts)]
pub struct SetPublisher<'info> {
    pub authority: Signer<'info>,
    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
}

/// Rotate the keeper key without touching anything already published.
pub fn handle_set_publisher(ctx: Context<SetPublisher>, publisher: Pubkey) -> Result<()> {
    require_keys_eq!(
        ctx.accounts.config.authority,
        ctx.accounts.authority.key(),
        ErrorCode::Unauthorized
    );
    ctx.accounts.config.publisher = publisher;
    msg!("publisher is now {}", publisher);
    Ok(())
}
