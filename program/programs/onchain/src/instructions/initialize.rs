use anchor_lang::prelude::*;

use crate::{constants::*, state::Config};

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        init,
        payer = payer,
        space = 8 + Config::INIT_SPACE,
        seeds = [CONFIG_SEED],
        bump
    )]
    pub config: Account<'info, Config>,
    pub system_program: Program<'info, System>,
}

/// Create the feed. The payer becomes the authority, and also the first
/// publisher, so a single key can run everything until a keeper key exists.
pub fn handle_initialize(ctx: Context<Initialize>, publisher: Pubkey) -> Result<()> {
    let config = &mut ctx.accounts.config;
    config.authority = ctx.accounts.payer.key();
    config.publisher = publisher;
    config.mark_count = 0;
    config.bump = ctx.bumps.config;
    msg!("crowd mark feed opened, publisher {}", publisher);
    Ok(())
}
