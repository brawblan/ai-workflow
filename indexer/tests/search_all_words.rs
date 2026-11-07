//! Tests of `search` with all words, phrases, the hit line, and `--max-bytes` (issue 282).

mod common;

use common::{Fixture, summary};

fn built(files: &[(&str, &str)]) -> Fixture {
    let fx = Fixture::new("allwords");
    for (path, text) in files {
        fx.write(path, text.as_bytes());
    }
    summary(&fx.build(&[]));
    fx
}

fn run(fx: &Fixture, args: &[&str]) -> (i32, String) {
    let out = fx.run_in(&fx.root, args);
    (out.status.code().unwrap(), common::stdout(&out))
}

#[test]
fn ac1_default_needs_all_words() {
    let fx = built(&[
        ("both.txt", "foo and bar\n"),
        ("one.txt", "foo only\n"),
        ("two.txt", "bar only\n"),
    ]);
    assert_eq!(
        run(&fx, &["search", "foo bar"]),
        (0, "both.txt:1: foo and bar\n".into())
    );
}

#[test]
fn ac1_words_may_be_on_different_lines_of_one_block() {
    let fx = built(&[("a.txt", "foo\nmiddle\nbar\n")]);
    assert_eq!(
        run(&fx, &["search", "foo bar"]),
        (0, "a.txt:1: foo\n".into())
    );
}

#[test]
fn ac1_no_block_has_all_words_exits_1() {
    let fx = built(&[("a.txt", "foo\n"), ("b.txt", "bar\n")]);
    assert_eq!(run(&fx, &["search", "foo bar"]), (1, String::new()));
}

#[test]
fn ac1_any_matches_at_least_one_word() {
    let fx = built(&[("a.txt", "foo\n"), ("b.txt", "bar\n"), ("c.txt", "baz\n")]);
    let (code, text) = run(&fx, &["search", "foo bar", "--any"]);
    assert_eq!(code, 0);
    let mut lines: Vec<&str> = text.lines().collect();
    lines.sort_unstable();
    assert_eq!(lines, vec!["a.txt:1: foo", "b.txt:1: bar"]);
}

#[test]
fn ac2_quoted_words_match_as_a_phrase_in_order() {
    let fx = built(&[
        ("in_order.txt", "the merge base of origin\n"),
        ("reversed.txt", "base merge origin\n"),
        ("apart.txt", "merge the base origin\n"),
    ]);
    assert_eq!(
        run(&fx, &["search", "\"merge base\" origin"]),
        (0, "in_order.txt:1: the merge base of origin\n".into())
    );
}

#[test]
fn ac2_phrase_alone() {
    let fx = built(&[("a.txt", "merge base\n"), ("b.txt", "base merge\n")]);
    assert_eq!(
        run(&fx, &["search", "\"merge base\""]),
        (0, "a.txt:1: merge base\n".into())
    );
}

#[test]
fn ac2_phrase_with_any() {
    let fx = built(&[
        ("a.txt", "merge base\n"),
        ("b.txt", "origin\n"),
        ("c.txt", "base merge\n"),
    ]);
    let (code, text) = run(&fx, &["search", "\"merge base\" origin", "--any"]);
    assert_eq!(code, 0);
    let mut lines: Vec<&str> = text.lines().collect();
    lines.sort_unstable();
    assert_eq!(lines, vec!["a.txt:1: merge base", "b.txt:1: origin"]);
}

#[test]
fn ac3_hit_line_is_the_line_with_most_terms() {
    let fx = built(&[("a.txt", "foo\nfoo bar\nbar\nfoo bar baz\n")]);
    assert_eq!(
        run(&fx, &["search", "foo bar"]),
        (0, "a.txt:2: foo bar\n".into())
    );
}

#[test]
fn ac3_tie_goes_to_the_first_line() {
    let fx = built(&[("a.txt", "x\nfoo\nbar\nfoo\n")]);
    assert_eq!(
        run(&fx, &["search", "foo bar"]),
        (0, "a.txt:2: foo\n".into())
    );
}

#[test]
fn ac3_phrase_counts_as_one_term() {
    let fx = built(&[("a.txt", "merge\nbase\nmerge base\norigin\n")]);
    assert_eq!(
        run(&fx, &["search", "\"merge base\" origin"]),
        (0, "a.txt:3: merge base\n".into())
    );
}

fn five_hits() -> Fixture {
    built(&[
        ("a.txt", "needle\n"),
        ("b.txt", "needle\n"),
        ("c.txt", "needle\n"),
        ("d.txt", "needle\n"),
        ("e.txt", "needle\n"),
    ])
}

#[test]
fn ac4_max_bytes_cuts_and_counts_not_printed_hits() {
    let fx = five_hits();
    // Each hit line is 16 bytes. 48 bytes hold 3.
    assert_eq!(
        run(&fx, &["search", "needle", "--max-bytes", "48", "--limit", "10"]),
        (
            0,
            "a.txt:1: needle\nb.txt:1: needle\nc.txt:1: needle\n(2 more results not printed. Use --limit or --max-bytes.)\n"
                .into()
        )
    );
}

#[test]
fn ac4_notice_is_not_counted_in_the_cap() {
    let fx = five_hits();
    let (_, text) = run(
        &fx,
        &["search", "needle", "--max-bytes", "48", "--limit", "10"],
    );
    let notice = text.lines().last().unwrap();
    assert!(notice.len() + 1 + 48 > 48 && text.len() > 48, "{text}");
    assert!(notice.starts_with("(2 more"), "{text}");
}

#[test]
fn ac4_cap_equal_to_the_hit_bytes_prints_them_all() {
    let fx = five_hits();
    let (code, text) = run(
        &fx,
        &["search", "needle", "--max-bytes", "80", "--limit", "10"],
    );
    assert_eq!(code, 0);
    assert_eq!(text.lines().count(), 5);
    assert!(!text.contains("more results"), "{text}");
    let (_, text) = run(
        &fx,
        &["search", "needle", "--max-bytes", "79", "--limit", "10"],
    );
    assert_eq!(text.lines().count(), 5, "{text}");
    assert!(
        text.ends_with("(1 more results not printed. Use --limit or --max-bytes.)\n"),
        "{text}"
    );
}

#[test]
fn ac4_n_includes_hits_omitted_by_limit() {
    let fx = five_hits();
    // limit 4: 4 rows, 1 omitted. The cap prints 3, so 2 are not printed.
    assert_eq!(
        run(&fx, &["search", "needle", "--max-bytes", "48", "--limit", "4"]),
        (
            0,
            "a.txt:1: needle\nb.txt:1: needle\nc.txt:1: needle\n(2 more results not printed. Use --limit or --max-bytes.)\n"
                .into()
        )
    );
}

#[test]
fn ac4_default_cap_is_4000_bytes() {
    let files: Vec<(String, String)> = (0..300)
        .map(|i| (format!("f{i:03}.txt"), "needle\n".to_string()))
        .collect();
    let refs: Vec<(&str, &str)> = files
        .iter()
        .map(|(p, t)| (p.as_str(), t.as_str()))
        .collect();
    let fx = built(&refs);
    let (code, text) = run(&fx, &["search", "needle", "--limit", "1000"]);
    assert_eq!(code, 0);
    let lines: Vec<&str> = text.lines().collect();
    let notice = *lines.last().unwrap();
    let hits = &lines[..lines.len() - 1];
    let hit_bytes: usize = hits.iter().map(|l| l.len() + 1).sum();
    assert!(hit_bytes <= 4000, "{hit_bytes}");
    assert!(hit_bytes + 19 > 4000, "{hit_bytes}");
    assert_eq!(
        notice,
        format!(
            "({} more results not printed. Use --limit or --max-bytes.)",
            300 - hits.len()
        )
    );
}

#[test]
fn ac4_json_is_not_capped() {
    let fx = five_hits();
    let (code, text) = run(
        &fx,
        &[
            "search",
            "needle",
            "--max-bytes",
            "10",
            "--limit",
            "10",
            "--format",
            "json",
        ],
    );
    assert_eq!(code, 0);
    assert_eq!(text.matches("\"path\"").count(), 5, "{text}");
    assert!(text.ends_with("\"omitted\":0}\n"), "{text}");
}

#[test]
fn ac4_max_bytes_needs_a_number() {
    let fx = five_hits();
    let (code, _) = run(&fx, &["search", "needle", "--max-bytes", "abc"]);
    assert_eq!(code, 2);
}
