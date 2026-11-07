import pytest


@pytest.mark.parametrize("spec", [
    ["src/context.py@head:1-2"], ["src/context.py@head", "1-2"],
    ["src/context.py@base:2"], ["src/context.py@base", "2"],
])
def test_show_ranges_use_git_line_numbers(changed, spec):
    output = changed.run("show", changed.out, *spec).stdout
    assert "     2  second = 2\n" in output
    assert "third = 3" not in output
    assert ("     1  first = 1\n" in output) == ("head" in spec[0])


@pytest.mark.parametrize("range_", ["0", "2-1", "4", "1-4"])
@pytest.mark.parametrize("inline", [False, True])
def test_show_rejects_zero_reversed_and_out_of_range(changed, range_, inline):
    spec = [f"src/context.py@head:{range_}"] if inline else ["src/context.py@head", range_]
    message = changed.run("show", changed.out, *spec, ok=False).stderr
    assert f"has 3 lines; {range_} is out of range" in message


def test_show_empty_file_retains_blank_separator(changed):
    output = changed.run("show", changed.out, "empty.txt@head", "src/context.py@head:1").stdout
    assert output.startswith("empty.txt@head  (empty)\n\nsrc/context.py@head  L1-1\n")
    assert "L1-0" not in output


def test_show_whole_file_has_no_phantom_final_line(changed):
    output = changed.run("show", changed.out, "src/context.py@head").stdout
    assert output == "src/context.py@head  L1-3\n     1  first = 1\n     2  second = 2\n     3  third = 3\n\n"


def test_show_directory_with_a_range_has_clear_message(changed):
    assert "src is a directory at head" in changed.run("show", changed.out, "src@head:1-2", ok=False).stderr
