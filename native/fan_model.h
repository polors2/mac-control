#pragma once
#include <math.h>
#include <stdbool.h>
#include <string.h>

// First-order thermal model: dT/dt = a + b*(T-40)/40 + c*load - d*fan.
// Exponentially weighted observations (~10 minutes) plus a ridge prior keep
// identification bounded when load and fan speed do not vary independently.
typedef struct {
    double gram[4][4], rhs[4], theta[4];
    double time, temperature, load, fan, slope, error;
    double forecast, headroom, demand;
    unsigned long samples;
    bool previous, safety;
} MCFanModel;

static double mcClamp(double x, double lo, double hi) { return fmax(lo, fmin(hi, x)); }
static const double mcPrior[4] = {.15, -.4, 1., .8};
static void mcModelInit(MCFanModel *m) {
    memset(m, 0, sizeof(*m));
    memcpy(m->theta, mcPrior, sizeof(mcPrior));
    m->demand = 1;
}
static void mcModelFit(MCFanModel *m, const double x[4], double rate, double dt) {
    double decay = exp(-dt / 600.), matrix[4][5];
    for (int i = 0; i < 4; i++) {
        m->rhs[i] = decay*m->rhs[i] + x[i]*rate;
        for (int j = 0; j < 4; j++) {
            m->gram[i][j] = decay*m->gram[i][j] + x[i]*x[j];
            matrix[i][j] = m->gram[i][j] + (i == j ? 5. : 0.);
        }
        matrix[i][4] = m->rhs[i] + 5.*mcPrior[i];
    }
    // Pivoted elimination of the small positive-definite, regularized system.
    for (int i = 0; i < 4; i++) {
        int pivot = i;
        for (int j = i+1; j < 4; j++) if (fabs(matrix[j][i]) > fabs(matrix[pivot][i])) pivot = j;
        for (int k = i; k < 5; k++) { double v = matrix[i][k]; matrix[i][k] = matrix[pivot][k]; matrix[pivot][k] = v; }
        if (!isfinite(matrix[i][i]) || fabs(matrix[i][i]) < 1e-9) return;
        double divisor = matrix[i][i];
        for (int k = i; k < 5; k++) matrix[i][k] /= divisor;
        for (int j = 0; j < 4; j++) if (j != i) {
            double factor = matrix[j][i];
            for (int k = i; k < 5; k++) matrix[j][k] -= factor*matrix[i][k];
        }
    }
    const double lower[] = {-2, -4, .05, .15}, upper[] = {2, -.02, 4, 4};
    for (int i = 0; i < 4; i++) m->theta[i] = mcClamp(matrix[i][4], lower[i], upper[i]);
    m->samples++;
}
// Returns false for invalid telemetry; callers must hand control back to Apple.
static bool mcModelStep(MCFanModel *m, double now, double temperature, double load,
                        double fan, double target) {
    if (!isfinite(now) || !isfinite(temperature) || temperature <= 0 || temperature >= 130 ||
        !isfinite(load) || load < 0 || load > 1 || !isfinite(fan) || fan < 0 || fan > 1 ||
        !isfinite(target) || target < 50 || target > 85) return false;
    double dt = now - m->time;
    bool continuous = m->previous && dt >= .5 && dt <= 6;
    double modeled = m->theta[0] + m->theta[1]*(temperature-40)/40 + m->theta[2]*load - m->theta[3]*fan;
    double rate = modeled;
    if (continuous) {
        double observed = (temperature - m->temperature)/dt;
        double x[] = {1, (m->temperature-40)/40, (load+m->load)/2, -(fan+m->fan)/2};
        double estimate = 0;
        for (int i = 0; i < 4; i++) estimate += m->theta[i]*x[i];
        m->error += (1-exp(-dt/60))*(fmin(5, fabs(observed-estimate))-m->error);
        // Spikes still drive cooling but do not teach an implausible heat model.
        if (fabs(observed) <= 3) mcModelFit(m, x, observed, dt);
        double alpha = 1-exp(-dt/4);
        m->slope += alpha*(mcClamp(observed, -5, 5)-m->slope);
        // Preserve unmodeled heat (GPU, ambient, etc.), anticipate rising CPU load.
        rate = fmax(m->slope, observed) + m->theta[2]*fmax(0, load-m->load);
    } else {
        m->slope = modeled;
        m->demand = 1; // New session / wake: cool conservatively, discard old trend.
    }
    const double horizon = 20;
    m->headroom = mcClamp(2 + 2*m->error, 2, 5);
    double goal = target - m->headroom;
    m->forecast = mcClamp(temperature + horizon*rate, 0, 150);
    // Solve T + H*(rate - d*(u-fan)) <= goal for u. Retain a
    // proportional floor so a noisy negative slope cannot prematurely coast.
    double desired = mcClamp(fan + (m->forecast-goal)/(horizon*m->theta[3]), 0, 1);
    desired = fmax(desired, mcClamp((temperature-(goal-12))/12, 0, 1)*.65);
    m->safety = temperature >= 90 || temperature >= target;
    double elapsed = continuous ? dt : 2;
    m->demand = m->safety ? 1 : mcClamp(desired, fmax(0, m->demand-.015*elapsed), fmin(1, m->demand+.15*elapsed));
    m->time = now; m->temperature = temperature; m->load = load; m->fan = fan; m->previous = true;
    return true;
}
