//! What the feed must refuse.
//!
//! A price feed is only as good as the readings it will not accept, so most of
//! these tests are about rejection: a stranger publishing, a probability above
//! one, a reading from the future, a stale reading, and an attempt to rewind a
//! mark to an older one.
use {
    anchor_lang::{
        prelude::Pubkey,
        solana_program::{clock::Clock, instruction::Instruction, system_program},
        AccountDeserialize, InstructionData, ToAccountMetas,
    },
    litesvm::LiteSVM,
    onchain::instructions::publish::PublishArgs,
    solana_keypair::Keypair,
    solana_message::{Message, VersionedMessage},
    solana_signer::Signer,
    solana_transaction::versioned::VersionedTransaction,
};

const ONE_SOL: u64 = 1_000_000_000;

fn program() -> (LiteSVM, Keypair, Pubkey) {
    let program_id = onchain::id();
    let mut svm = LiteSVM::new();
    let bytes = include_bytes!(concat!(env!("CARGO_TARGET_TMPDIR"), "/../deploy/onchain.so"));
    svm.add_program(program_id, bytes).unwrap();
    let payer = Keypair::new();
    svm.airdrop(&payer.pubkey(), 10 * ONE_SOL).unwrap();
    set_clock(&mut svm, 1_789_900_000);     // 21 Sep 2026, a plausible now
    (svm, payer, program_id)
}

fn config_pda(program_id: &Pubkey) -> Pubkey {
    Pubkey::find_program_address(&[onchain::constants::CONFIG_SEED], program_id).0
}

fn mark_pda(program_id: &Pubkey, symbol: &str) -> Pubkey {
    Pubkey::find_program_address(
        &[onchain::constants::MARK_SEED, symbol.as_bytes()],
        program_id,
    )
    .0
}

fn send(
    svm: &mut LiteSVM,
    signers: &[&Keypair],
    payer: &Pubkey,
    ix: Instruction,
) -> std::result::Result<(), String> {
    let blockhash = svm.latest_blockhash();
    let msg = Message::new_with_blockhash(&[ix], Some(payer), &blockhash);
    let tx = VersionedTransaction::try_new(VersionedMessage::Legacy(msg), signers).unwrap();
    svm.send_transaction(tx)
        .map(|_| ())
        .map_err(|e| format!("{:?}", e))
}

/// LiteSVM starts with a clock at zero, which is not a time any real chain
/// reports. Set a believable one so the freshness rules are actually tested.
fn set_clock(svm: &mut LiteSVM, unix_timestamp: i64) {
    let mut clock = svm.get_sysvar::<Clock>();
    clock.unix_timestamp = unix_timestamp;
    svm.set_sysvar::<Clock>(&clock);
}

fn now_of(svm: &LiteSVM) -> i64 {
    svm.get_sysvar::<Clock>().unix_timestamp
}

fn init(svm: &mut LiteSVM, payer: &Keypair, program_id: &Pubkey, publisher: Pubkey) {
    let ix = Instruction::new_with_bytes(
        *program_id,
        &onchain::instruction::Initialize { publisher }.data(),
        onchain::accounts::Initialize {
            payer: payer.pubkey(),
            config: config_pda(program_id),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    );
    send(svm, &[payer], &payer.pubkey(), ix).expect("initialize should succeed");
}

/// A believable Anthropic reading: token at $1,045, the crowd at $2.23T.
fn good_args(now: i64) -> PublishArgs {
    PublishArgs {
        company: "Anthropic".to_string(),
        kind: 0,
        token_price_micro: 1_045_240_000,
        token_implied_cents: 171_200_000_000_000,
        crowd_value_cents: 223_000_000_000_000,
        crowd_low_cents: 221_000_000_000_000,
        crowd_high_cents: 225_000_000_000_000,
        crowd_per_token_micro: 1_358_390_000,
        p_event_bps: 9_340,
        open_top_mass_bps: 620,
        next_deadline: now + 70 * 86_400,
        next_deadline_bps: 5_400,
        source_read_at: now,
        sources_hash: [7u8; 32],
    }
}

fn publish_ix(
    program_id: &Pubkey,
    publisher: &Pubkey,
    symbol: &str,
    args: PublishArgs,
) -> Instruction {
    Instruction::new_with_bytes(
        *program_id,
        &onchain::instruction::Publish {
            symbol: symbol.to_string(),
            args,
        }
        .data(),
        onchain::accounts::Publish {
            publisher: *publisher,
            config: config_pda(program_id),
            mark: mark_pda(program_id, symbol),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    )
}

#[test]
fn publishes_and_stores_exactly_what_was_sent() {
    let (mut svm, payer, program_id) = program();
    init(&mut svm, &payer, &program_id, payer.pubkey());
    let now = now_of(&svm);

    let args = good_args(now);
    let ix = publish_ix(&program_id, &payer.pubkey(), "ANTHROPIC", args.clone());
    send(&mut svm, &[&payer], &payer.pubkey(), ix).expect("publish should succeed");

    let acc = svm.get_account(&mark_pda(&program_id, "ANTHROPIC")).unwrap();
    let mut data: &[u8] = &acc.data;
    let mark = onchain::state::Mark::try_deserialize(&mut data).unwrap();

    assert_eq!(mark.symbol, "ANTHROPIC");
    assert_eq!(mark.company, "Anthropic");
    assert_eq!(mark.crowd_value_cents, args.crowd_value_cents);
    assert_eq!(mark.token_implied_cents, args.token_implied_cents);
    assert_eq!(mark.p_event_bps, args.p_event_bps);
    assert_eq!(mark.sources_hash, args.sources_hash);
    assert_eq!(mark.source_read_at, now);
    assert!(mark.published_at >= now, "published_at comes from the chain");
    assert!(!mark.is_stale(mark.published_at), "a fresh mark is not stale");
    assert!(
        mark.is_stale(mark.published_at + onchain::state::Mark::MAX_AGE_SECONDS + 1),
        "an old mark reports itself stale"
    );

    let cfg_acc = svm.get_account(&config_pda(&program_id)).unwrap();
    let mut cfg_data: &[u8] = &cfg_acc.data;
    let cfg = onchain::state::Config::try_deserialize(&mut cfg_data).unwrap();
    assert_eq!(cfg.mark_count, 1);
}

#[test]
fn anyone_may_publish_and_the_feed_records_who_did() {
    let (mut svm, payer, program_id) = program();
    let keeper = Keypair::new();
    init(&mut svm, &payer, &program_id, keeper.pubkey());
    let now = now_of(&svm);

    // A wallet nobody configured, which is the point of an open feed.
    let stranger = Keypair::new();
    svm.airdrop(&stranger.pubkey(), ONE_SOL).unwrap();
    let ix = publish_ix(&program_id, &stranger.pubkey(), "ANTHROPIC", good_args(now));
    send(&mut svm, &[&stranger], &stranger.pubkey(), ix).expect("a stranger may publish");

    let acc = svm.get_account(&mark_pda(&program_id, "ANTHROPIC")).unwrap();
    let mut data: &[u8] = &acc.data;
    let mark = onchain::state::Mark::try_deserialize(&mut data).unwrap();
    assert_eq!(mark.last_publisher, stranger.pubkey(), "the feed records who refreshed it");
    assert_eq!(mark.publish_count, 1);

    // The rules still bite, whoever is signing.
    let mut bad = good_args(now);
    bad.p_event_bps = 10_001;
    let ix = publish_ix(&program_id, &stranger.pubkey(), "ANTHROPIC", bad);
    assert!(
        send(&mut svm, &[&stranger], &stranger.pubkey(), ix).is_err(),
        "an open feed still refuses an impossible reading"
    );
}

#[test]
fn refuses_impossible_and_backdated_readings() {
    let (mut svm, payer, program_id) = program();
    init(&mut svm, &payer, &program_id, payer.pubkey());
    let now = now_of(&svm);

    // A probability above one.
    let mut args = good_args(now);
    args.p_event_bps = 10_001;
    let ix = publish_ix(&program_id, &payer.pubkey(), "OPENAI", args);
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "a probability above one must fail"
    );

    // A reading from the future.
    let mut args = good_args(now);
    args.source_read_at = now + 10_000;
    let ix = publish_ix(&program_id, &payer.pubkey(), "OPENAI", args);
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "a future reading must fail"
    );

    // A reading older than an hour.
    let mut args = good_args(now);
    args.source_read_at = now - 7_200;
    let ix = publish_ix(&program_id, &payer.pubkey(), "OPENAI", args);
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "a stale reading must fail"
    );

    // A value outside the range it states for itself.
    let mut args = good_args(now);
    args.crowd_value_cents = args.crowd_high_cents + 1;
    let ix = publish_ix(&program_id, &payer.pubkey(), "OPENAI", args);
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "a value outside its range must fail"
    );

    // A lower-case symbol.
    let ix = publish_ix(&program_id, &payer.pubkey(), "openai", good_args(now));
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "a lower-case symbol must fail"
    );
}

#[test]
fn a_mark_cannot_be_rewound() {
    let (mut svm, payer, program_id) = program();
    init(&mut svm, &payer, &program_id, payer.pubkey());
    let now = now_of(&svm);

    let ix = publish_ix(&program_id, &payer.pubkey(), "ANTHROPIC", good_args(now));
    send(&mut svm, &[&payer], &payer.pubkey(), ix).expect("first publish");

    // The same reading time says nothing new.
    let ix = publish_ix(&program_id, &payer.pubkey(), "ANTHROPIC", good_args(now));
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "republishing the same reading must fail"
    );

    // An older reading than the one stored.
    let mut older = good_args(now);
    older.source_read_at = now - 600;
    let ix = publish_ix(&program_id, &payer.pubkey(), "ANTHROPIC", older);
    assert!(
        send(&mut svm, &[&payer], &payer.pubkey(), ix).is_err(),
        "an older reading must fail"
    );

    // A newer one is accepted, and the company is not counted twice.
    let mut newer = good_args(now);
    newer.source_read_at = now + 1;
    newer.crowd_value_cents = 224_000_000_000_000;
    let ix = publish_ix(&program_id, &payer.pubkey(), "ANTHROPIC", newer);
    send(&mut svm, &[&payer], &payer.pubkey(), ix).expect("a newer reading is accepted");

    let cfg_acc = svm.get_account(&config_pda(&program_id)).unwrap();
    let mut cfg_data: &[u8] = &cfg_acc.data;
    let cfg = onchain::state::Config::try_deserialize(&mut cfg_data).unwrap();
    assert_eq!(cfg.mark_count, 1, "updating a company must not count it twice");
}

#[test]
fn only_the_authority_rotates_the_publisher() {
    let (mut svm, payer, program_id) = program();
    init(&mut svm, &payer, &program_id, payer.pubkey());

    let keeper = Keypair::new();
    let intruder = Keypair::new();
    svm.airdrop(&intruder.pubkey(), ONE_SOL).unwrap();

    let ix = Instruction::new_with_bytes(
        program_id,
        &onchain::instruction::SetPublisher {
            publisher: keeper.pubkey(),
        }
        .data(),
        onchain::accounts::SetPublisher {
            authority: intruder.pubkey(),
            config: config_pda(&program_id),
        }
        .to_account_metas(None),
    );
    assert!(
        send(&mut svm, &[&intruder], &intruder.pubkey(), ix).is_err(),
        "an intruder must not rotate the publisher"
    );

    let ix = Instruction::new_with_bytes(
        program_id,
        &onchain::instruction::SetPublisher {
            publisher: keeper.pubkey(),
        }
        .data(),
        onchain::accounts::SetPublisher {
            authority: payer.pubkey(),
            config: config_pda(&program_id),
        }
        .to_account_metas(None),
    );
    send(&mut svm, &[&payer], &payer.pubkey(), ix).expect("the authority may rotate it");

    let cfg_acc = svm.get_account(&config_pda(&program_id)).unwrap();
    let mut cfg_data: &[u8] = &cfg_acc.data;
    let cfg = onchain::state::Config::try_deserialize(&mut cfg_data).unwrap();
    assert_eq!(cfg.publisher, keeper.pubkey());
}
