// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

export function productLocationTable(locations) {
    var $table = $(`
        <div class="frappe-dialog-table-container">
        <table class="table table-bordered table-hover">
            <thead>
            <tr>
                <th>Product</th>
                <th>Warehouse Location</th>
                <th>Quantity</th>
            </tr>
            </thead>
            <tbody>
            </tbody>
        </table>
        </div>

        <style>
        .frappe-dialog-table-container {
            margin: 0 0;
            overflow-x: auto;
        }

        .frappe-dialog-table-container table {
            width: 100%;
            margin-top: 0;
            margin-bottom: 0;
            font-size: 13px;
        }
        </style>
    `)

    locations.forEach(function(row) { // Add row for each location
        var $row = $('<tr>')
            .append($('<td>').text(row.product))
            .append($('<td>').text(row.parent))
            .append($('<td style="text-align: right;">').text(row.quantity));
        $table.find('tbody').append($row);
    });

    return $table
} 