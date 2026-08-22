"""Whether a validated candidate is *eligible* for promotion (plan step 8).

Eligibility is not promotion. ADR 0004 keeps promotion a manual act, and
nothing here activates anything: this decides whether an administrator is
allowed to promote, and gives them the comparison they need to decide
whether they should. A candidate that clears every threshold still waits for
a human.
"""

from dataclasses import dataclass, field

from fuel_predictor.domain.model_package import ManifestMetrics, ModelPackageManifest


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Thresholds a candidate must clear before an operator may promote it.

    `max_mae_liters` is an absolute ceiling; `max_mae_regression_ratio` bounds
    how much worse than the current active model a candidate may be. Both
    exist because either alone is gameable: an absolute ceiling alone accepts
    a clear regression that still sits under it, and a relative bound alone
    accepts unbounded drift downward as long as each step is small.
    """

    max_mae_liters: float
    max_mae_regression_ratio: float = 1.0
    minimum_test_set_size: int = 30


@dataclass(frozen=True, slots=True)
class PromotionEligibility:
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        if self.eligible and not self.warnings:
            return "Kandidat memenuhi kebijakan promosi."
        if self.eligible:
            return "Kandidat memenuhi kebijakan promosi, dengan catatan."
        return "Kandidat belum memenuhi kebijakan promosi."


@dataclass(frozen=True, slots=True)
class EvaluateCandidateAgainstPolicy:
    policy: PromotionPolicy

    def execute(
        self,
        manifest: ModelPackageManifest,
        active_metrics: ManifestMetrics | None,
    ) -> PromotionEligibility:
        reasons: list[str] = []
        warnings: list[str] = []
        candidate = manifest.overall_metrics

        if candidate.mae > self.policy.max_mae_liters:
            reasons.append(
                f"MAE kandidat {candidate.mae:g} L melebihi ambang "
                f"{self.policy.max_mae_liters:g} L."
            )

        if manifest.test_set_size < self.policy.minimum_test_set_size:
            reasons.append(
                f"Ukuran set uji {manifest.test_set_size} di bawah minimum "
                f"{self.policy.minimum_test_set_size}; metrik belum cukup dapat dipercaya."
            )

        if active_metrics is None:
            # Nothing to regress against. Say so explicitly rather than
            # letting the absence read as "no regression detected".
            warnings.append(
                "Belum ada model aktif untuk dibandingkan; metrik kandidat berdiri sendiri."
            )
        else:
            reasons.extend(self._regression_reasons(candidate, active_metrics))
            warnings.extend(self._coverage_warnings(candidate, active_metrics))

        return PromotionEligibility(
            eligible=not reasons, reasons=tuple(reasons), warnings=tuple(warnings)
        )

    def _regression_reasons(
        self, candidate: ManifestMetrics, active: ManifestMetrics
    ) -> list[str]:
        if active.mae <= 0:
            # A zero or negative active MAE makes a ratio meaningless; compare
            # absolutely instead of dividing by something that cannot be a
            # sensible denominator.
            if candidate.mae > active.mae:
                return [
                    f"MAE kandidat {candidate.mae:g} L lebih buruk daripada model aktif "
                    f"{active.mae:g} L."
                ]
            return []

        ratio = candidate.mae / active.mae
        if ratio > self.policy.max_mae_regression_ratio:
            return [
                f"MAE kandidat {candidate.mae:g} L adalah {ratio:.2f}x model aktif "
                f"{active.mae:g} L, melebihi batas "
                f"{self.policy.max_mae_regression_ratio:.2f}x."
            ]
        return []

    def _coverage_warnings(
        self, candidate: ManifestMetrics, active: ManifestMetrics
    ) -> list[str]:
        # Interval coverage dropping is worth flagging but is not on its own a
        # reason to block: a better point estimate with slightly worse
        # calibration can still be the right model to promote, and that
        # trade-off is a judgement for the operator, not this policy.
        if candidate.interval_coverage_percent < active.interval_coverage_percent - 5:
            return [
                f"Cakupan interval turun dari {active.interval_coverage_percent:g}% "
                f"ke {candidate.interval_coverage_percent:g}%."
            ]
        return []
