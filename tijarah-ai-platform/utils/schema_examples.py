"""
utils/schema_examples.py
-------------------------
Few-shot examples fed into the AI Advisor's SQL-generation prompt.
These ground the model in the real schema and column names, which
significantly reduces hallucinated tables/columns.
"""

EXAMPLES = """
Question:
Top 5 customers by revenue

SQL:
SELECT TOP 5 dc.CustomerName AS customer, SUM(f.LineTotal) AS revenue
FROM FactSales f
JOIN DimCustomer dc ON f.CustomerKey = dc.CustomerKey
GROUP BY dc.CustomerName
ORDER BY revenue DESC

Question:
Top selling products

SQL:
SELECT TOP 10 dp.Product, SUM(f.LineTotal) AS revenue
FROM FactSales f
JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
GROUP BY dp.Product
ORDER BY revenue DESC

Question:
Products that need reordering

SQL:
SELECT dp.Product, fi.CurrentStock, fi.ReorderLevel
FROM FactInventory fi
JOIN DimProduct dp ON fi.ProductKey = dp.ProductKey
WHERE fi.CurrentStock <= fi.ReorderLevel
ORDER BY (fi.ReorderLevel - fi.CurrentStock) DESC

Question:
Top suppliers by spend this year

SQL:
SELECT TOP 10 ds.SupplierName AS supplier,
       SUM(fp.QuantityOrdered * fp.UnitCostPrice) AS total_spend
FROM FactPurchases fp
JOIN DimSupplier ds ON fp.SupplierKey = ds.SupplierKey
JOIN DimDate d ON fp.PurchaseDateKey = d.DateKey
WHERE d.YearNumber = (SELECT MAX(YearNumber) FROM DimDate)
GROUP BY ds.SupplierName
ORDER BY total_spend DESC

Question:
Monthly sales trend

SQL:
SELECT d.MonthName + ' ' + CAST(d.YearNumber AS VARCHAR) AS period,
       SUM(f.LineTotal) AS revenue
FROM FactSales f
JOIN DimDate d ON f.InvoiceDateKey = d.DateKey
GROUP BY d.YearNumber, d.MonthNumber, d.MonthName
ORDER BY d.YearNumber, d.MonthNumber

Question:
Sales by category

SQL:
SELECT dp.Category, SUM(f.LineTotal) AS revenue
FROM FactSales f
JOIN DimProduct dp ON f.ProductKey = dp.ProductKey
GROUP BY dp.Category
ORDER BY revenue DESC
"""
