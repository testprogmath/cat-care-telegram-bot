"""Any text a chat can hold: the classifiers and normalisers that read it must not raise."""

import sys

import atheris

with atheris.instrument_imports():
    from skrypka_bot import classify, foods, meds


def test_one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(512)
    classify.toilet_kind(text)
    classify.is_failed_toilet(text)
    classify.is_recap(text)
    classify.reports_vomiting(text)
    foods.product(text, fdp.PickValueInList([True, False, None]))
    dose = meds.normalise_dose(text)
    meds.dose_amount(dose or text)
    meds.dose_en(dose or text)
    meds.label_en(text)


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
